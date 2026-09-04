# Fix operario.html
f1 = 'operario.html'
c1 = open(f1, encoding='utf-8').read()
c1 = c1.replace("showScreen('screen-register')", "showScreen('register')")
c1 = c1.replace("showScreen('screen-login')", "showScreen('login')")
with open(f1, 'w', encoding='utf-8') as f:
    f.write(c1)

# Fix main.py
f2 = 'bot/main.py'
c2 = open(f2, encoding='utf-8').read()
c2 = c2.replace('model_name="gemini-1.5-flash"', 'model_name="gemini-1.5-flash-latest"')
with open(f2, 'w', encoding='utf-8') as f:
    f.write(c2)
