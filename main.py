# -*- coding: utf-8 -*-
import os
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
# 표시/삭제 정책
# ========================
# True  → 모든 응답/메뉴를 '나만 보이게(ephemeral)'
# False → 공개로 보내고, 아래 AUTO_DELETE_SECONDS 후 자동삭제
USE_EPHEMERAL = True
AUTO_DELETE_SECONDS = 300  # 5분

# ========================
# 이모지(유니코드: 서버 상관없이 정상)
# ========================
EMO = {
    "ok": "✅",
    "warn": "⚠️",
    "err": "❌",
}

# ========================
# 임베드 유틸(검정, 시간표시 제거)
# ========================
COLOR_BLACK = discord.Color.from_rgb(0, 0, 0)

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
# 공통 응답 헬퍼
# ========================
async def send_interaction(inter: Interaction, *, embed: discord.Embed, view: View | None = None):
    # 이미 응답했는지 체크
    if USE_EPHEMERAL:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await inter.followup.send(embed=embed, view=view, ephemeral=True)
    else:
        if not inter.response.is_done():
            await inter.response.send_message(embed=embed, view=view, delete_after=AUTO_DELETE_SECONDS)
        else:
            await inter.followup.send(embed=embed, view=view, delete_after=AUTO_DELETE_SECONDS)

# ========================
# 모달: 쿠키 검증
# ========================
class CookieModal(Modal, title="쿠키 검증"):
    cookie = TextInput(label=".ROBLOSECURITY 쿠키", style=TextStyle.short)

    async def on_submit(self, inter: Interaction):
        embed = make_embed()
        try:
            async with aiohttp.ClientSession(cookies={'.ROBLOSECURITY': self.cookie.value}) as session:
                async with session.get('https://users.roblox.com/v1/users/authenticated') as resp:
                    text = await resp.text()
                    if '"id":' in text:
                        embed.set_author(name=f"{EMO['ok']} 유효한 쿠키")
                        embed.add_field(name="결과", value="쿠키가 유효합니다.", inline=False)
                    elif 'Unauthorized' in text or resp.status == 401:
                        embed.set_author(name=f"{EMO['err']} 유효하지 않은 쿠키")
                        embed.add_field(name="결과", value="쿠키가 유효하지 않습니다.", inline=False)
                    else:
                        embed.set_author(name=f"{EMO['warn']} 오류 발생")
                        embed.add_field(name="서버 응답", value=f"```\n{text}\n```", inline=False)
        except Exception as e:
            embed.set_author(name=f"{EMO['err']} 요청 실패")
            embed.add_field(name="에러", value=f"```\n{e}\n```", inline=False)

        await send_interaction(inter, embed=embed)

# ========================
# 모달: 전체 계정 정보 조회
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

        await send_interaction(inter, embed=embed)

# ========================
# 버튼 뷰(회색 버튼 2개)
# ========================
class CheckView(View):
    @discord.ui.button(label="쿠키검증", style=discord.ButtonStyle.secondary)
    async def b1(self, inter: Interaction, button: discord.ui.Button):
        await inter.response.send_modal(CookieModal())

    @discord.ui.button(label="전체조회", style=discord.ButtonStyle.secondary)
    async def b2(self, inter: Interaction, button: discord.ui.Button):
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
                print(f"[SYNC] 글로벌 동기화: {len(synced)}개 (전파 지연 가능)")
        except Exception as e:
            print("[SYNC] 실패:", e)

bot = MyBot()

@bot.event
async def on_ready():
    print(f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC → 로그인: {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Cookie Checker"))

@bot.tree.command(name="체킹", description="로블록스 쿠키 및 정보 체킹 메뉴")
async def check(inter: Interaction):
    # 메뉴 자체도 위 정책 따라감
    if USE_EPHEMERAL:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(), ephemeral=True)
    else:
        await inter.response.send_message(embed=main_menu_embed(), view=CheckView(), delete_after=AUTO_DELETE_SECONDS)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("환경변수 DISCORD_TOKEN 이 설정되지 않았습니다.")
    bot.run(TOKEN)
