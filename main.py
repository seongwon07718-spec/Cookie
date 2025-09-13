import os, asyncio, random, string
import discord
from discord import app_commands

# ===== 환경변수 =====
TOKEN = os.getenv("DISCORD_TOKEN")

# ===== 컬러(다크/검정 톤) =====
COLOR_DARK = 0x0a0a0a
COLOR_ACCENT = 0x111111
COLOR_WARN = 0x1d1d1d
COLOR_SUCCESS = 0x121212

# ===== 임베드 헬퍼 =====
def eb(title, desc, color=COLOR_DARK):
    return discord.Embed(title=title, description=desc, color=color)

def gen_ticket_id():
    import string, random
    return 'TICKET-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ===== Bot 준비 =====
intents = discord.Intents.default()
intents.guilds = True
intents.members = True

class TicketBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.db = None  # aiosqlite 연결 핸들

    async def setup_hook(self):
        # DB 초기화
        import aiosqlite
        self.db = await aiosqlite.connect('ticket.db')
        await self.db.execute('''
        CREATE TABLE IF NOT EXISTS settings(
            guild_id TEXT PRIMARY KEY,
            manager_role_id TEXT,
            category_id TEXT,
            log_channel_id TEXT
        )''')
        await self.db.execute('''
        CREATE TABLE IF NOT EXISTS open_tickets(
            guild_id TEXT,
            user_id TEXT,
            channel_id TEXT,
            owner_user_id TEXT,
            PRIMARY KEY (guild_id, user_id)
        )''')
        await self.db.commit()
        await self.tree.sync()

bot = TicketBot()

# ===== DB 유틸 =====
async def get_settings(guild_id):
    cur = await bot.db.execute(
        'SELECT manager_role_id, category_id, log_channel_id FROM settings WHERE guild_id=?',
        (str(guild_id),)
    )
    row = await cur.fetchone()
    return row

async def upsert_settings(guild_id, manager_role_id, category_id, log_channel_id):
    await bot.db.execute('''
    INSERT INTO settings(guild_id, manager_role_id, category_id, log_channel_id)
    VALUES(?,?,?,?)
    ON CONFLICT(guild_id) DO UPDATE SET
        manager_role_id=excluded.manager_role_id,
        category_id=excluded.category_id,
        log_channel_id=excluded.log_channel_id
    ''', (str(guild_id), manager_role_id, category_id, log_channel_id))
    await bot.db.commit()

async def get_open_ticket(guild_id, user_id):
    cur = await bot.db.execute(
        'SELECT channel_id FROM open_tickets WHERE guild_id=? AND user_id=?',
        (str(guild_id), str(user_id))
    )
    row = await cur.fetchone()
    return row[0] if row else None

async def add_open_ticket(guild_id, user_id, channel_id, owner_user_id):
    await bot.db.execute(
        'INSERT OR REPLACE INTO open_tickets(guild_id, user_id, channel_id, owner_user_id) VALUES(?,?,?,?)',
        (str(guild_id), str(user_id), str(channel_id), str(owner_user_id))
    )
    await bot.db.commit()

async def remove_open_ticket_by_owner(guild_id, owner_user_id):
    await bot.db.execute(
        'DELETE FROM open_tickets WHERE guild_id=? AND owner_user_id=?',
        (str(guild_id), str(owner_user_id))
    )
    await bot.db.commit()

# ===== View들 =====
class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='티켓 생성', style=discord.ButtonStyle.primary, custom_id='ticket_create')
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await get_settings(interaction.guild_id)
        if not row:
            await interaction.response.send_message(embed=eb('미설정', '아직 설정이 안 돼 있어. /설정_메뉴 먼저.'), ephemeral=True)
            return
        manager_role_id, category_id, log_channel_id = row

        existing = await get_open_ticket(interaction.guild_id, interaction.user.id)
        if existing:
            ch = interaction.guild.get_channel(int(existing))
            msg = f'이미 열린 티켓이 있어: {ch.mention}' if ch else '기존 티켓 레코드가 남아있어. 관리자에게 문의해줘.'
            await interaction.response.send_message(embed=eb('중복 방지', msg, COLOR_WARN), ephemeral=True)
            return

        category = interaction.guild.get_channel(int(category_id)) if category_id else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
        }
        role = None
        if manager_role_id:
            role = interaction.guild.get_role(int(manager_role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

        ticket_id = gen_ticket_id()
        # 채널 이름: 닉네임 대신 ID 쓰고 싶으면 아래 라인 교체
        # name = f'ticket-{ticket_id.lower()}'
        name = f'ticket-{interaction.user.name}'.lower()
        channel = await interaction.guild.create_text_channel(name=name, category=category, overwrites=overwrites)

        await add_open_ticket(interaction.guild_id, interaction.user.id, channel.id, interaction.user.id)

        manager_role_mention = role.mention if role else ''
        first = eb(
            '티켓이 생성되었습니다',
            f'안녕하세요, {interaction.user.mention}! 문의 내용을 작성해줘. 관리자가 곧 응답할 거야.\n\n티켓 ID: {ticket_id}',
            COLOR_ACCENT
        )
        close_view = TicketCloseView(owner_id=interaction.user.id, ticket_id=ticket_id)
        await channel.send(
            content=(' '.join(x for x in [interaction.user.mention, manager_role_mention] if x)).strip(),
            embed=first,
            view=close_view
        )

        jump = f'https://discord.com/channels/{interaction.guild_id}/{channel.id}'
        go_view = discord.ui.View()
        go_view.add_item(discord.ui.Button(label='티켓 바로가기', url=jump, style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=eb('티켓 생성 완료', f'{channel.mention}에서 이어서 대화해줘.', COLOR_SUCCESS), view=go_view, ephemeral=True)

        if log_channel_id:
            log_ch = interaction.guild.get_channel(int(log_channel_id))
            if log_ch:
                await log_ch.send(embed=eb('티켓 생성 로그', f'[{ticket_id}] {channel.mention} by {interaction.user.mention}', COLOR_ACCENT))

class TicketCloseView(discord.ui.View):
    def __init__(self, owner_id: int, ticket_id: str):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.ticket_id = ticket_id

    @discord.ui.button(label='티켓 닫기', style=discord.ButtonStyle.danger, custom_id='ticket_close')
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await get_settings(interaction.guild_id)
        manager_role_id = row[0] if row else None

        is_owner = interaction.user.id == self.owner_id
        is_manager = False
        if manager_role_id and isinstance(interaction.user, discord.Member):
            is_manager = discord.utils.get(interaction.user.roles, id=int(manager_role_id)) is not None

        if not (is_owner or is_manager):
            await interaction.response.send_message(embed=eb('권한 없음', '이 티켓을 닫을 권한이 없어.', COLOR_WARN), ephemeral=True)
            return

        confirm_embed = eb('티켓 닫기', '정말로 닫을래? 닫으면 5초 후에 채널이 삭제돼.', COLOR_WARN)
        view = CloseConfirmView(owner_id=self.owner_id, ticket_id=self.ticket_id)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)

class CloseConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, ticket_id: str):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.ticket_id = ticket_id

    @discord.ui.button(label='확인', style=discord.ButtonStyle.danger, custom_id='confirm_close')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await get_settings(interaction.guild_id)
        manager_role_id = row[0] if row else None

        is_owner = interaction.user.id == self.owner_id
        is_manager = False
        if manager_role_id and isinstance(interaction.user, discord.Member):
            is_manager = discord.utils.get(interaction.user.roles, id=int(manager_role_id)) is not None
        if not (is_owner or is_manager):
            await interaction.response.edit_message(embed=eb('권한 없음', '이 티켓을 닫을 권한이 없어.', COLOR_WARN), view=None)
            return

        await interaction.response.edit_message(embed=eb('처리 중', '티켓을 닫는 중이야...', COLOR_ACCENT), view=None)

        try:
            closing = eb('티켓 닫힘', f'이 티켓은 {interaction.user.mention}에 의해 닫혔어. 5초 후에 채널이 삭제돼.', COLOR_SUCCESS)
            await interaction.channel.send(embed=closing)
        except:
            pass

        log_channel_id = row[2] if row else None
        if log_channel_id:
            log_ch = interaction.guild.get_channel(int(log_channel_id))
            if log_ch:
                await log_ch.send(embed=eb('티켓 닫힘 로그', f'[{self.ticket_id}] <#{interaction.channel_id}> by {interaction.user.mention}', COLOR_ACCENT))

        await remove_open_ticket_by_owner(interaction.guild_id, self.owner_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason='Ticket closed')
        except:
            pass

    @discord.ui.button(label='취소', style=discord.ButtonStyle.secondary, custom_id='cancel_close')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=eb('취소됨', '닫기를 취소했어.', COLOR_ACCENT), view=None)

# ===== 설정 메뉴 View =====
class SettingMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label='티켓 관리자 역할 설정', style=discord.ButtonStyle.secondary, custom_id='set_manager_role')
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=eb('권한 부족', '서버 관리 권한이 필요해.'), ephemeral=True)
            return

        options = []
        for r in interaction.guild.roles:
            if r.is_default():
                continue
            options.append(discord.SelectOption(label=r.name[:90], value=str(r.id)))
        if not options:
            await interaction.response.send_message(embed=eb('역할 없음', '설정할 역할이 없네.'), ephemeral=True)
            return

        select = discord.ui.Select(placeholder='관리자 역할 선택', options=options[:25], custom_id='select_manager_role')
        view = discord.ui.View()

        async def on_select(i: discord.Interaction):
            role_id = select.values[0]
            row = await get_settings(i.guild_id) or (None, None, None)
            _, category_id, log_channel_id = row
            await upsert_settings(i.guild_id, role_id, category_id, log_channel_id)
            await i.response.edit_message(embed=eb('저장 완료', f'관리자 역할이 <@&{role_id}> 로 저장됐어.', COLOR_SUCCESS), view=None)

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(embed=eb('관리자 역할', '관리자 역할을 골라줘.', COLOR_ACCENT), view=view, ephemeral=True)

    @discord.ui.button(label='티켓 카테고리 설정', style=discord.ButtonStyle.secondary, custom_id='set_category')
    async def set_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=eb('권한 부족', '서버 관리 권한이 필요해.'), ephemeral=True)
            return

        cats = [c for c in interaction.guild.channels if isinstance(c, discord.CategoryChannel)]
        options = [discord.SelectOption(label=c.name[:90], value=str(c.id)) for c in cats]
        if not options:
            await interaction.response.send_message(embed=eb('카테고리 없음', '카테고리가 없어. 하나 만들어줘.'), ephemeral=True)
            return

        select = discord.ui.Select(placeholder='카테고리 선택', options=options[:25], custom_id='select_category')
        view = discord.ui.View()

        async def on_select(i: discord.Interaction):
            category_id = select.values[0]
            row = await get_settings(i.guild_id) or (None, None, None)
            manager_role_id, _, log_channel_id = row
            await upsert_settings(i.guild_id, manager_role_id, category_id, log_channel_id)
            await i.response.edit_message(embed=eb('저장 완료', f'카테고리가 <#{category_id}> 로 저장됐어.', COLOR_SUCCESS), view=None)

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(embed=eb('카테고리', '티켓이 만들어질 카테고리를 골라줘.', COLOR_ACCENT), view=view, ephemeral=True)

    @discord.ui.button(label='로그 채널 설정', style=discord.ButtonStyle.secondary, custom_id='set_log_channel')
    async def set_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=eb('권한 부족', '서버 관리 권한이 필요해.'), ephemeral=True)
            return

        texts = [c for c in interaction.guild.text_channels]
        options = [discord.SelectOption(label=c.name[:90], value=str(c.id)) for c in texts]
        if not options:
            await interaction.response.send_message(embed=eb('채널 없음', '텍스트 채널이 없네.'), ephemeral=True)
            return

        select = discord.ui.Select(placeholder='로그 채널 선택', options=options[:25], custom_id='select_log')
        view = discord.ui.View()

        async def on_select(i: discord.Interaction):
            log_id = select.values[0]
            row = await get_settings(i.guild_id) or (None, None, None)
            manager_role_id, category_id, _ = row
            await upsert_settings(i.guild_id, manager_role_id, category_id, log_id)
            await i.response.edit_message(embed=eb('저장 완료', f'로그 채널이 <#{log_id}> 로 저장됐어.', COLOR_SUCCESS), view=None)

        select.callback = on_select
        view.add_item(select)
        await interaction.response.send_message(embed=eb('로그 채널', '로그를 보낼 채널을 골라줘.', COLOR_ACCENT), view=view, ephemeral=True)

# ===== Slash Commands =====
@bot.tree.command(name='설정', description='티켓 설정을 확인합니다.')
async def 설정_cmd(interaction: discord.Interaction):
    await 설정(interaction)

@bot.tree.command(name='설정_메뉴', description='기본 설정 메뉴를 띄웁니다.')
async def 설정_메뉴(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(embed=eb('권한 부족', '서버 관리 권한이 필요해.'), ephemeral=True)
        return
    await interaction.response.send_message(embed=eb('기본 설정', '아래 버튼에서 항목을 선택해 설정해줘.', COLOR_ACCENT), view=SettingMenu(), ephemeral=True)

@bot.tree.command(name='티켓_임베드_생성', description='티켓 생성 버튼 임베드를 보냅니다.')
@app_commands.describe(채널='임베드를 보낼 채널')
async def 티켓_임베드_생성(interaction: discord.Interaction, 채널: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(embed=eb('권한 부족', '서버 관리 권한이 필요해.'), ephemeral=True)
        return
    await 채널.send(embed=eb('티켓 생성', '아래 버튼을 눌러 티켓을 만들어줘.', COLOR_ACCENT), view=TicketCreateView())
    await interaction.response.send_message(embed=eb('성공', f'티켓 임베드가 {채널.mention}에 생성됐어.', COLOR_SUCCESS), ephemeral=True)

# ===== 영속 View 등록 =====
@bot.event
async def on_connect():
    bot.add_view(TicketCreateView())
    bot.add_view(SettingMenu())

# ===== 시작 =====
if __name__ == '__main__':
    if not TOKEN or TOKEN.strip() == '':
        raise RuntimeError('DISCORD_TOKEN 환경변수가 비어있어. 토큰을 설정해줘.')
    bot.run(TOKEN)
