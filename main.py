ent = False
bot = commands.Bot(command_prefix="!", intents=INTENTS)

GUILD_ID = int(os.getenv("GUILD_ID"))

CFG_PATH = Path("ticket_config.json")
DEFAULT_CFG = {
    "manager_role_id": os.getenv("TICKET_MANAGER_ROLE_ID") or "",
    "category_id": os.getenv("TICKET_CATEGORY_ID") or "",
    "log_channel_id": os.getenv("LOG_CHANNEL_ID") or "",
    "save_transcript": (os.getenv("SAVE_TRANSCRIPT","true").lower()=="true"),
    "archive_channel_id": os.getenv("ARCHIVE_CHANNEL_ID") or "",
    # 메인 임베드 문
    "embed_title": "문의하기",
    "embed_desc": "아래 버튼을 눌러 문의를 시작해주세요.",
    "embed_thumb": "",
    "embed_footer": ""
}

def load_cfg():
    if CFG_PATH.exists():
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = DEFAULT_CFG.copy()
        CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    for k,v in DEFAULT_CFG.items():
        if k not in cfg: cfg[k]=v
    return cfg

def save_cfg(cfg):
    CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

CFG = load_cfg()

# ===== 색/유틸 =====
# 회색 톤(디스코드 다크 UI와 잘 어울리는 차콜)
GRAY_COLOR          = 0x2B2D31  # 메인/생성/기본 카드
GOLD_COLOR          = 0xF1C40F  # 닫기 확인(카운트다운) 강조 라인
GREEN_COLOR         = 0x2ECC71  # 닫힘 완료 카드

def gray_embed(title: str, desc: str=""):
    return discord.Embed(title=title, description=desc, color=GRAY_COLOR)

def color_embed(title: str, desc: str, color: int):
    return discord.Embed(title=title, description=desc, color=color & 0xFFFFFF)

async def defer_once(inter: discord.Interaction, ephemeral=True):
    if not inter.response.is_done():
        await inter.response.defer(ephemeral=ephemeral)

def sanitize_for_channel(s: str) -> str:
    s = (s or "").lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "x"

def sanitize_username(name: str) -> str:
    return sanitize_for_channel(name)[:20] or "user"

# ===== 부팅: 커맨드 리셋(권한 없으면 우회 동기화) =====
@bot.event
async def on_ready():
    print(f"로그인: {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    try:
        await bot.http.request(
            discord.http.Route("PUT","/applications/{app_id}/guilds/{guild_id}/commands",
                               app_id=bot.application_id, guild_id=GUILD_ID),
            json=[]
        )
        await bot.tree.sync(guild=guild)
        print("슬래시 리셋 및 재등록 완료")
    except Exception as e:
        print("슬래시 초기화 실패(우회 동기화):", e)
        with contextlib.suppress(Exception):
            await bot.tree.sync(guild=guild)
            print("우회 동기화 완료")

# ===== 설정 컴포넌트 =====
class ManagerRoleSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="관리자 역할 선택", min_values=1, max_values=1, custom_id="select_manager_role")
    async def callback(self, interaction):
        await defer_once(interaction, ephemeral=True)
        role = self.values[0]
        CFG["manager_role_id"] = str(role.id); save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("설정 완료", f"관리자 역할: {role.mention}"), ephemeral=True)

class CategoryChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(channel_types=[discord.ChannelType.category], placeholder="티켓 카테고리 선택", min_values=1, max_values=1, custom_id="select_category")
    async def callback(self, interaction):
        await defer_once(interaction, ephemeral=True)
        cat = self.values[0]
        CFG["category_id"] = str(cat.id); save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("설정 완료", f"티켓 카테고리: {cat.name}"), ephemeral=True)

class LogTextChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(channel_types=[discord.ChannelType.text], placeholder="티켓 로그 채널 선택", min_values=1, max_values=1, custom_id="select_log")
    async def callback(self, interaction):
        await defer_once(interaction, ephemeral=True)
        ch = self.values[0]
        CFG["log_channel_id"] = str(ch.id); save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("설정 완료", f"티켓 로그 채널: {ch.mention}"), ephemeral=True)

class ArchiveChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(channel_types=[discord.ChannelType.text], placeholder="티켓 보관 채널 선택", min_values=1, max_values=1, custom_id="select_archive")
    async def callback(self, interaction):
        await defer_once(interaction, ephemeral=True)
        ch = self.values[0]
        CFG["archive_channel_id"] = str(ch.id); save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("설정 완료", f"티켓 보관 채널: {ch.mention}"), ephemeral=True)

class MainEmbedEditModal(discord.ui.Modal, title="메인 임베드 편집"):
    def __init__(self):
        super().__init__()
        self.ti = discord.ui.TextInput(label="제목", default=CFG.get("embed_title","문의하기"), max_length=100)
        self.de = discord.ui.TextInput(label="본문(설명)", style=discord.TextStyle.paragraph, default=CFG.get("embed_desc","아래 버튼을 눌러 문의를 시작해주세요."), max_length=1000, required=False)
        self.th = discord.ui.TextInput(label="썸네일 URL(선택)", default=CFG.get("embed_thumb",""), required=False)
        self.fo = discord.ui.TextInput(label="풋터(선택)", default=CFG.get("embed_footer",""), max_length=100, required=False)
        self.add_item(self.ti); self.add_item(self.de); self.add_item(self.th); self.add_item(self.fo)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        CFG["embed_title"] = str(self.ti.value).strip() or "문의하기"
        CFG["embed_desc"]  = str(self.de.value).strip() or "아래 버튼을 눌러 문의를 시작해주세요."
        CFG["embed_thumb"] = str(self.th.value).strip()
        CFG["embed_footer"]= str(self.fo.value).strip()
        save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("저장 완료", "메인 임베드 문구가 업데이트 됐습니다."), ephemeral=True)

class TranscriptToggleSelect(discord.ui.Select):
    def __init__(self):
        label = "보관 끄기" if CFG.get("save_transcript") else "보관 켜기"
        super().__init__(placeholder="티켓 보관 On/Off", min_values=1, max_values=1,
                         options=[discord.SelectOption(label=label, value="toggle", emoji="🔁")],
                         custom_id="ts_toggle")
    async def callback(self, interaction):
        await defer_once(interaction, ephemeral=True)
        CFG["save_transcript"] = not CFG.get("save_transcript"); save_cfg(CFG)
        await interaction.followup.send(embed=gray_embed("변경되었습니다", f"티켓 보관: {'켜짐' if CFG['save_transcript'] else '꺼짐'}"), ephemeral=True)
        if CFG["save_transcript"]:
            v = discord.ui.View(timeout=180); v.add_item(ArchiveChannelSelect())
            await interaction.followup.send(embed=gray_embed("티켓 보관 채널 선택","아래에서 티켓 보관 채널을 선택하세요."), view=v, ephemeral=True)

class SettingsMainSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="설정 작업 선택",
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(label="관리자 역할 설정", value="set_manager", emoji="👑"),
                discord.SelectOption(label="티켓 카테고리 설정", value="set_category", emoji="🗂️"),
                discord.SelectOption(label="티켓 로그 채널 설정", value="set_log", emoji="🔒"),
                discord.SelectOption(label="티켓 보관 설정", value="transcript", emoji="📁"),
                discord.SelectOption(label="메인 임베드 편집", value="edit_main_embed", emoji="📝"),
            ],
            custom_id="settings_main"
        )
    async def callback(self, interaction):
        sel = self.values[0]
        if sel == "set_manager":
            v = discord.ui.View(timeout=180); v.add_item(ManagerRoleSelect())
            return await interaction.response.send_message(embed=gray_embed("관리자 역할 설정","아래에서 역할을 선택하세요."), view=v, ephemeral=True)
        if sel == "set_category":
            v = discord.ui.View(timeout=180); v.add_item(CategoryChannelSelect())
            return await interaction.response.send_message(embed=gray_embed("티켓 카테고리 설정","아래에서 티켓 카테고리를 선택하세요."), view=v, ephemeral=True)
        if sel == "set_log":
            v = discord.ui.View(timeout=180); v.add_item(LogTextChannelSelect())
            return await interaction.response.send_message(embed=gray_embed("티켓 로그 채널 설정","아래에서 티켓 로그 채널을 선택하세요."), view=v, ephemeral=True)
        if sel == "transcript":
            v = discord.ui.View(timeout=180); v.add_item(TranscriptToggleSelect())
            return await interaction.response.send_message(embed=gray_embed("티켓 보관 설정", f"현재 상태: {'켜짐' if CFG.get('save_transcript') else '꺼짐'}\n보관 채널: {('<#'+CFG['archive_channel_id']+'>') if CFG.get('archive_channel_id') else '미설정'}"), view=v, ephemeral=True)
        if sel == "edit_main_embed":
            return await interaction.response.send_modal(MainEmbedEditModal())

class SettingsMainView(discord.ui.View):
    def __init__(self, timeout=300):
        super().__init__(timeout=timeout)
        self.add_item(SettingsMainSelect())

@bot.tree.command(name="티켓_설정", description="티켓 설정 패널", guild=discord.Object(id=GUILD_ID))
async def settings_cmd(interaction):
    await defer_once(interaction, ephemeral=True)
    manager_line = f"<@&{CFG['manager_role_id']}>" if CFG.get("manager_role_id") else "예시"
    category_line = f"{CFG['category_id']}" if CFG.get("category_id") else "예시"
    log_line = f"<#{CFG['log_channel_id']}>" if CFG.get("log_channel_id") else "예시"
    trans_line = f"{'켜짐' if CFG.get('save_transcript') else '꺼짐'} / {('<#'+CFG['archive_channel_id']+'>') if CFG.get('archive_channel_id') else '미설정'}"
    desc =("티켓 관리자 역할\n"
            f"{manager_line}\n\n"
            "티켓 카테고리\n"
            f"{category_line}\n\n"
            "티켓 로그 채널\n"
            f"{log_line}\n\n"
            "티켓 보관\n"
            f"{trans_line}\n\n"
            "아래 드롭다운에서 작업을 선택하세요.")
    await interaction.followup.send(embed=gray_embed("티켓 설정하기", desc), view=SettingsMainView(), ephemeral=True)

# ===== 메인 임베드: 드롭다운 제거, 문의하기(회색) 버튼 =====
BTN_OPEN_INQUIRY = "open_inquiry"
BTN_CLOSE_MAIN   = "close_ticket_main"
BTN_CLOSE_YES    = "close_ticket_yes"
BTN_CLOSE_NO     = "close_ticket_no"

class InquiryButtonView(discord.ui.View):
    def __init__(self, timeout=300):
        super().__init__(timeout=timeout)
        # 문의하기 버튼 라벨/색 수정: 회색 유지 + 📝
        self.add_item(discord.ui.Button(label="📝 문의하기", style=discord.ButtonStyle.secondary, custom_id=BTN_OPEN_INQUIRY))

@bot.tree.command(name="티켓_임베드_생성", description="문의하기 버튼 임베드를 이 채널에 올렸습니다.", guild=discord.Object(id=GUILD_ID))
async def embed_create(interaction: discord.Interaction):
    try:
        await defer_once(interaction, ephemeral=True)
        emb = discord.Embed(
            title=CFG.get("embed_title","📝 문의하기"),
            description=CFG.get("embed_desc","아래 버튼을 눌러 문의를 시작해주세요."),
            color=GRAY_COLOR
        )
        thumb = CFG.get("embed_thumb"); footer=CFG.get("embed_footer")
        if thumb:
            with contextlib.suppress(Exception):
                emb.set_thumbnail(url=thumb)
        if footer:
            emb.set_footer(text=footer)
        await interaction.channel.send(embed=emb, view=InquiryButtonView())
        await interaction.followup.send(embed=gray_embed("완료","문의하기 버튼 임베드를 올렸습니다."), ephemeral=True)
    except Exception as e:
        print("embed_create error:", e)
        await interaction.followup.send(embed=gray_embed("오류","임베드 생성 중 오류 발생"), ephemeral=True)

# ===== 티켓 열기/닫기 =====
@bot.tree.command(name="티켓_열기", description="새 티켓을 즉시 엽니다.", guild=discord.Object(id=GUILD_ID))
async def open_cmd(interaction):
    try:
        await open_ticket(interaction, interaction.user, "수동 생성")
    except Exception as e:
        print("open_cmd error:", e)
        await defer_once(interaction, ephemeral=True)
        await interaction.followup.send(embed=gray_embed("오류","티켓 생성 중 오류 발생"), ephemeral=True)

@bot.tree.command(name="티켓_닫기", description="현재 티켓을 닫습니다.", guild=discord.Object(id=GUILD_ID))
async def close_cmd(interaction):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or not ch.name.lower().startswith("ticket-"):
        return await interaction.response.send_message(embed=gray_embed("오류","여긴 티켓 채널이 아닙니다."), ephemeral=True)
    await send_close_confirm(interaction, seconds=30)

async def send_close_confirm(interaction: discord.Interaction, seconds: int = 30):
    await defer_once(interaction, ephemeral=True)
    emb = color_embed(
        "티켓 닫기",
        f"정말로 이 티켓을 닫으시겠습니까? 티켓을 닫으면 {seconds}초 후에 채널이 삭제됩니다.",
        GOLD_COLOR  # 노란 라인 느낌
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="확인", style=discord.ButtonStyle.danger, custom_id=BTN_CLOSE_YES))
    view.add_item(discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary, custom_id=BTN_CLOSE_NO))
    msg = await interaction.followup.send(embed=emb, view=view, ephemeral=True)

    try:
        for left in range(seconds-1, -1, -1):
            await asyncio.sleep(1)
            try:
                emb.description = f"정말로 이 티켓을 닫으시겠습니까? 티켓을 닫으면 {left}초 후에 채널이 삭제됩니다."
                await msg.edit(embed=emb, view=view)
            except Exception:
                break
    except Exception:
        pass

# ===== 버튼 핸들러 =====
@bot.event
async def on_interaction(inter: discord.Interaction):
    try:
        if inter.type != discord.InteractionType.component:
            return
        cid = inter.data.get("custom_id")
        ch  = inter.channel

        if cid == BTN_OPEN_INQUIRY:
            await defer_once(inter, ephemeral=True)
            return await open_ticket(inter, inter.user, "문의하기 버튼")

        if cid == BTN_CLOSE_MAIN:
            if not isinstance(ch, discord.TextChannel) or not ch.name.lower().startswith("ticket-"):
                return await inter.response.send_message(embed=gray_embed("오류","여긴 티켓 채널이 아닙니다."), ephemeral=True)
            return await send_close_confirm(inter, seconds=30)

        if cid == BTN_CLOSE_YES:
            if not isinstance(ch, discord.TextChannel) or not ch.name.lower().startswith("ticket-"):
                if not inter.response.is_done():
                    return await inter.response.send_message(embed=gray_embed("오류","티켓 채널만 가능합니다."), ephemeral=True)
                else:
                    return await inter.followup.send(embed=gray_embed("오류","티켓 채널만 가능합니다."), ephemeral=True)
            await defer_once(inter, ephemeral=True)
            await ch.send(embed=color_embed("티켓 닫힘",
                                            f"{inter.user.mention}에 의해 닫혔습니다. 3초 후 채널이 삭제됩니다.",
                                            GREEN_COLOR))
            await inter.followup.send(embed=gray_embed("처리 완료","3초 후 채널이 삭제됩니다."), ephemeral=True)
            await save_transcript_and_delete(ch, closed_by=inter.user, delay=3)
            return

        if cid == BTN_CLOSE_NO:
            if not inter.response.is_done():
                await inter.response.send_message(embed=gray_embed("취소","닫기를 취소했습니다."), ephemeral=True)
            else:
                await inter.followup.send(embed=gray_embed("취소","닫기를 취소했습니다."), ephemeral=True)
            return

    except Exception as e:
        print("on_interaction error:", e)
        if not inter.response.is_done():
            with contextlib.suppress(Exception):
                await inter.response.send_message(embed=gray_embed("오류","버튼 처리 중 오류 발생"), ephemeral=True)
        else:
            with contextlib.suppress(Exception):
                await inter.followup.send(embed=gray_embed("오류","버튼 처리 중 오류 발생"), ephemeral=True)

# ===== 티켓 생성 + 트랜스크립트 =====
async def open_ticket(interaction, user, reason: str):
    guild = interaction.guild
    if not CFG.get("category_id") or not CFG.get("manager_role_id"):
        await defer_once(interaction, ephemeral=True)
        return await interaction.followup.send(embed=gray_embed("설정 필요","먼저 /설정에서 관리자 역할과 카테고리를 지정해주세요"), ephemeral=True)

    # [추가] 동일 유저의 열린 티켓 중복 방지
    try:
        for ch in guild.text_channels:
            if not isinstance(ch, discord.TextChannel):
                continue
            if not ch.name.lower().startswith("ticket-"):
                continue
            perm = ch.permissions_for(user)
            if perm.view_channel:
                await defer_once(interaction, ephemeral=True)
                return await interaction.followup.send(
                    embed=gray_embed("이미 열린 티켓이 있어요", f"{ch.mention}에서 이어서 대화해주세요."),
                    ephemeral=True
                )
    except Exception:
        pass

    uname = sanitize_username(getattr(user,"name","user"))
    base = f"ticket-{uname}"
    names = {c.name for c in guild.text_channels}
    final_name = base; i=2
    while final_name in names:
        final_name = f"{base}-{i}"; i += 1

    category = guild.get_channel(int(CFG["category_id"])) if CFG.get("category_id") else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    }
    role = guild.get_role(int(CFG["manager_role_id"])) if CFG.get("manager_role_id") else None
    if role:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
        )

    ch = await guild.create_text_channel(
        name=final_name,
        category=category if isinstance(category, discord.CategoryChannel) else None,
        overwrites=overwrites
    )

    main_view = discord.ui.View()
    # 닫기 버튼을 빨간색으로 변경
    main_view.add_item(discord.ui.Button(label="티켓 닫기", style=discord.ButtonStyle.danger, custom_id=BTN_CLOSE_MAIN, emoji="🔒"))

    await ch.send(
        content=f"{user.mention} {(role.mention if role else '')}".strip(),
        embed=discord.Embed(
            title="티켓이 생성되었습니다",
            description=f"안녕하세요, {user.mention}! 문의 내용을 작성해주세요.",
            color=GRAY_COLOR
        ),
        view=main_view
    )

    jump = discord.ui.View()
    jump.add_item(discord.ui.Button(label="💌 티켓 바로가기", style=discord.ButtonStyle.link, url=f"https://discord.com/channels/{guild.id}/{ch.id}"))
    await defer_once(interaction, ephemeral=True)
    await interaction.followup.send(embed=gray_embed("티켓 생성 완료", f"{ch.mention} 티켓이 생성되었습니다."), view=jump, ephemeral=True)

    if CFG.get("log_channel_id"):
        log = guild.get_channel(int(CFG["log_channel_id"]))
        if log:
            await log.send(embed=gray_embed("티켓 생성 로그", f"채널: {ch.mention}\n요청자: {user}\n사유: {reason}"))

async def save_transcript_and_delete(ch: discord.TextChannel, closed_by: discord.User, delay: int=5):
    try:
        await asyncio.sleep(delay)
        if CFG.get("save_transcript"):
            buf = io.StringIO()
            msgs = [m async for m in ch.history(limit=None, oldest_first=True)]
            for m in msgs:
                author = f"{m.author}({m.author.id})"
                ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = m.content or ""
                if m.embeds: content += " [EMBED]"
                if m.attachments:
                    atts = " ".join(a.url for a in m.attachments)
                    content += f" [ATTACHMENTS: {atts}]"
                buf.write(f"[{ts}] {author}: {content}\n")
            data = buf.getvalue().encode("utf-8")
            file = discord.File(io.BytesIO(data), filename=f"{ch.name}.txt")

            with contextlib.suppress(Exception):
                await ch.send(embed=gray_embed("티켓 보관","채널 기록을 txt로 저장했습니다."), file=file)

            if CFG.get("archive_channel_id"):
                archive = ch.guild.get_channel(int(CFG["archive_channel_id"]))
                if archive:
                    await archive.send(embed=gray_embed("티켓 보관", f"채널: {ch.mention}\n종료자: {closed_by}"),
                                       file=discord.File(io.BytesIO(data), filename=f"{ch.name}.txt"))

            if CFG.get("log_channel_id"):
                log = ch.guild.get_channel(int(CFG["log_channel_id"]))
                if log:
                    await log.send(embed=gray_embed("티켓 종료 로그", f"채널: {ch.mention}\n종료자: {closed_by}"))

        with contextlib.suppress(Exception):
            await ch.delete()
    except Exception as e:
        print("save_transcript_and_delete error:", e)
        with contextlib.suppress(Exception):
            await ch.delete()

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
