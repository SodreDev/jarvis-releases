src = open('main.py', encoding='utf-8').read()
n = src.count('"""')
print('triple-quote count:', n, 'parity:', n % 2)
# Find positions
import re
matches = [(m.start(), src[max(0,m.start()-30):m.start()].splitlines()[-1] if src[max(0,m.start()-30):m.start()].splitlines() else '') for m in re.finditer('"""', src)]
print('first 30 positions:')
lines = src.split('\n')
for m in re.finditer('"""', src):
    line_no = src[:m.start()].count('\n') + 1
    if 5170 <= line_no <= 5180:
        print(line_no, lines[line_no-1][:100])
