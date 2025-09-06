# -*- coding: utf-8 -*
import os
import asyncio
import aiohttp
import datetime as dt

import discord
from discord.ext import commands
from discord import app_commands
from discord import Interaction, TextStyle
from discord.ui import View, Modal, TextInput

# ========================
# 환경변수
# ========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 선택: 숫자만 입력(따옴표 X). 없으면 글로벌 싱크

# ========================
# 이모지 매핑(커스텀)
# ========================
EMO = {
    "ok": "<a:emoji_8:1411690712344301650>",     # ✅ 대체
    "warn": "<:wehum:1396746268868608041>",       # ⚠️ 대체
    "err": "<a:emoji_7:1411690688403345528>",     # ❌ 대체
}

# ========================
# 색상/임베드 유틸(검정)
# ========================
COLOR_BLACK = discord.Color.from_rgb(0, 0, 0)

def white_embed() -> discord.Embed:
    now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # 요청 시간은 푸터 텍스트로만 표시(임베드 timestamp 사용 안 함)
    return discord.Embed(color=COLOR_BLACK).set_footer(text=f"요청 시간: {now_str} UTC")

# ========================
# 모달들
# ========================
class CookieModal(Modal, title="쿠키 검증"):
    cookie = TextInput(label=".ROBLOSECURITY 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = white_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as resp:
                    text = await resp.text()
                    if '"id":' in text:
                        embed.set_author(name=f"{EMO['ok']} 유효한 쿠키").add_field(name="결과", value="쿠키가 유효합니다.", inline=False)
                    elif 'Unauthorized' in text or resp.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키").add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생").add_field(name="서버 응답", value=f"```\n{text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패").add_field(name="에러", value=f"```\n{e}\n```", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


class RobuxModal(Modal, title="로벅스 조회"):
    cookie = TextInput(label=".ROBLOSECURITY 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = white_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as auth_res:
                    auth_text = await auth_res.text()
                    if '"id":' in auth_text:
                        user_id = (await auth_res.json())['id']
                        async with session.get(f'https://economy.roblox.com/v1/users/{user_id}/currency') as robux_res:
                            data = await robux_res.json()
                            robux = data.get('robux', 0)
                        embed.set_author(name=f"{EMO['ok']} 로벅스 정보").add_field(name="보유 로벅스", value=f"{robux} R$", inline=False)
                    elif 'Unauthorized' in auth_text or auth_res.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키").add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생").add_field(name="서버 응답", value=f"```\n{auth_text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패").add_field(name="에러", value=f"```\n{e}\n```", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


class AvatarModal(Modal, title="아바타 이미지 조회"):
    cookie = TextInput(label=".ROBLOSECURITY 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = white_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as auth_res:
                    auth_text = await auth_res.text()
                    if '"id":' in auth_text:
                        user_id = (await auth_res.json())['id']
                        thumb_url = f'https://thumbnails.roblox.com/v1/users/avatar?size=720x720&format=png&userIds={user_id}'
                        async with session.get(thumb_url) as thumb_res:
                            thumb = (await thumb_res.json()).get('data', [{}])[0].get('imageUrl', 'N/A')
                        embed.set_author(name=f"{EMO['ok']} 아바타 이미지").set_image(url=thumb)
                    elif 'Unauthorized' in auth_text or auth_res.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키").add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생").add_field(name="서버 응답", value=f"```\n{auth_text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패").add_field(name="에러", value=f"```\n{e}\n```", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


class ItemModal(Modal, title="게임 아이템 조회"):
    cookie = TextInput(label=".ROBLOSECURITY 쿠키", style=TextStyle.short)
    item_id = TextInput(label="아이템 ID", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = white_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as auth_res:
                    auth_text = await auth_res.text()
                    if '"id":' in auth_text:
                        user_id = (await auth_res.json())['id']
                        url = f'https://inventory.roblox.com/v1/users/{user_id}/items/Asset/{self.item_id.value}'
                        async with session.get(url) as item_res:
                            item_data = await item_res.json()
                        if item_data.get('data'):
                            embed.set_author(name=f"{EMO['ok']} 아이템 보유 확인").add_field(
                                name="결과", value=f"사용자는 아이템 ID `{self.item_id.value}`를 보유하고 있습니다.", inline=False
                            )
                        else:
                            embed.set_author(name=f"{EMO['err']} 아이템 미보유").add_field(
                                name="결과", value=f"사용자는 아이템 ID `{self.item_id.value}`를 보유하고 있지 않습니다.", inline=False
                            )
                    elif 'Unauthorized' in auth_text or auth_res.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키").add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생").add_field(name="서버 응답", value=f"```\n{auth_text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패").add_field(name="에러", value=f"```\n{e}\n```", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


class TotalCheckModal(Modal, title="전체 계정 정보 조회"):
    cookie = TextInput(label="로블록스 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = white_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as auth_res:
                    auth_text = await auth_res.text()
                    if '"id":' in auth_text:
                        user_id = (await auth_res.json())['id']

                        async def fetch_json(url: str):
                            async with session.get(url) as r:
                                return await r.json()

                        robux_task = fetch_json(f'https://economy.roblox.com/v1/users/{user_id}/currency')
                        credit_task = fetch_json('https://billing.roblox.com/v1/credit')
                        settings_task = fetch_json('https://www.roblox.com/my/settings/json')
                        friends_task = fetch_json('https://friends.roblox.com/v1/my/friends/count')
                        voice_task = fetch_json('https://voice.roblox.com/v1/settings')
                        thumb_task = fetch_json(
                            f'https://thumbnails.roblox.com/v1/users/avatar-headshot?size=48x48&format=png&userIds={user_id}'
                        )

                        robux, credit, settings_data, friends, voice, thumb = await asyncio.gather(
                            robux_task, credit_task, settings_task, friends_task, voice_task, thumb_task
                        )

                        embed.set_author(name=f"{EMO['ok']} 전체 계정 정보").set_thumbnail(
                            url=thumb.get('data', [{}])[0].get('imageUrl', 'N/A')
                        )
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
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키").add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생").add_field(name="서버 응답", value=f"```\n{auth_text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패").add_field(name="에러", value=f"```\n{e}\n```", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)

# ========================
# 버튼 뷰
# ========================
class CheckView(View):
    @discord.ui.button(label="쿠키검증", style=discord.ButtonStyle.primary)
    async def b1(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(CookieModal())

    @discord.ui.button(label="로벅스조회", style=discord.ButtonStyle.primary)
    async def b2(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(RobuxModal())

    @discord.ui.button(label="아바타조회", style=discord.ButtonStyle.primary)
    async def b3(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(AvatarModal())

    @discord.ui.button(label="아이템조회", style=discord.ButtonStyle.primary)
    async def b4(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(ItemModal())

    @discord.ui.button(label="전체조회", style=discord.ButtonStyle.primary)
    async def b6(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(TotalCheckModal())

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
                print(f"[SYNC] 글로벌 동기화: {len(synced)}개 (전파에 수 분 소요 가능)")
        except Exception as e:
            print("[SYNC] 실패:", e)

bot = MyBot()

@bot.event
async def on_ready():
    now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now_str} UTC → 로그인: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="로블록스 쿠키 체커봇"))

@bot.tree.command(name="체킹", description="로블록스 쿠키 및 정보 체킹 메뉴")
async def check(inter: Interaction):
    await inter.response.send_message(
        embed=white_embed().set_author(name="체킹 메뉴"),
        view=CheckView(),
        ephemeral=True
    )

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
