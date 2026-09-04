import re
import os

def update_auth(html_file, is_operario):
    content = open(html_file, encoding='utf-8').read()
    
    if is_operario:
        login_btn = '<button class="btn-primary" onclick="opLogin()">🔐 Ingresar al Sistema</button>'
        reg_btn = '<div style="text-align:center; margin-top:10px;"><a href="#" onclick="showScreen(\'screen-register\')" style="color:var(--accent); font-size:13px; text-decoration:none;">Crear cuenta nueva</a></div>'
        if 'Crear cuenta nueva' not in content:
            content = content.replace(login_btn, login_btn + '\n    ' + reg_btn)
            
        reg_screen = '''
  <div class="screen" id="screen-register">
    <div class="app-icon">🏭</div>
    <div class="app-name">Smart<span>WMS</span></div>
    <div class="role-badge">Registro Operario</div>
    <div class="inp-group">
      <label>Correo Electrónico</label>
      <input id="reg-email" type="email" placeholder="operario@smartwms.cl" />
    </div>
    <div class="inp-group">
      <label>Contraseña</label>
      <input id="reg-pass" type="password" placeholder="••••••••" />
    </div>
    <button class="btn-primary" onclick="opRegister()">Crear Cuenta</button>
    <div style="text-align:center; margin-top:10px;"><a href="#" onclick="showScreen(\'screen-login\')" style="color:var(--accent); font-size:13px; text-decoration:none;">Volver al login</a></div>
  </div>'''
        if 'screen-register' not in content:
            content = content.replace('<div class="screen" id="screen-home">', reg_screen + '\n\n  <div class="screen" id="screen-home">')

        js_login = '''
async function opLogin() {
  const email = document.getElementById('op-user').value.trim();
  const pass = document.getElementById('op-pin').value.trim();
  if(!email || !pass) return alert('Completa los campos');
  try {
    const res = await fetch('http://127.0.0.1:8000/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: pass })
    });
    if(res.ok) {
       const data = await res.json();
       localStorage.setItem('token', data.access_token);
       showScreen('screen-home');
    } else {
       alert('Credenciales incorrectas');
    }
  } catch(e) { alert('Error de conexión'); }
}

async function opRegister() {
  const email = document.getElementById('reg-email').value.trim();
  const pass = document.getElementById('reg-pass').value.trim();
  if(!email || !pass) return alert('Completa los campos');
  try {
    const res = await fetch('http://127.0.0.1:8000/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: pass, role: 'operario' })
    });
    if(res.ok) {
       alert('Registro exitoso. Ahora inicia sesión.');
       showScreen('screen-login');
    } else {
       const data = await res.json();
       alert(data.detail || 'Error en registro');
    }
  } catch(e) { alert('Error de conexión'); }
}'''
        content = re.sub(r'function opLogin\(\) \{.*?(?=function showScreen)', js_login + '\n\n', content, flags=re.DOTALL)
        
    else:
        login_btn = '<button class="btn-login" id="btn-login-sup" onclick="doLogin()">Iniciar Sesión</button>'
        reg_btn = '<div style="text-align:center; margin-top:10px;"><a href="#" onclick="showSupRegister()" style="color:var(--accent); font-size:13px; text-decoration:none;">Crear cuenta nueva</a></div>'
        if 'Crear cuenta nueva' not in content:
            content = content.replace(login_btn, login_btn + '\n    ' + reg_btn)
            
        js_login = '''
function showSupRegister() {
  const isReg = document.getElementById('btn-login-sup').textContent === 'Crear Cuenta';
  if(isReg) {
     document.getElementById('btn-login-sup').textContent = 'Iniciar Sesión';
     document.getElementById('btn-login-sup').onclick = doLogin;
     document.querySelector('.login-subtitle').textContent = 'Plataforma de gestión de bodega inteligente. Ingresa tus credenciales para continuar.';
  } else {
     document.getElementById('btn-login-sup').textContent = 'Crear Cuenta';
     document.getElementById('btn-login-sup').onclick = doRegister;
     document.querySelector('.login-subtitle').textContent = 'Registro de Supervisor.';
  }
}

async function doLogin() {
  const email = document.getElementById('login-email').value;
  const pass = document.getElementById('login-pass').value;
  try {
    const res = await fetch('http://127.0.0.1:8000/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: pass })
    });
    if(res.ok) {
       const data = await res.json();
       localStorage.setItem('token', data.access_token);
       document.getElementById('login-screen').style.display='none';
       document.getElementById('app').style.display='flex';
       updateClock(); setInterval(updateClock,1000);
       initCharts();
    } else {
       document.getElementById('login-error').style.display='block';
    }
  } catch(e) { alert('Error de conexión'); }
}

async function doRegister() {
  const email = document.getElementById('login-email').value;
  const pass = document.getElementById('login-pass').value;
  try {
    const res = await fetch('http://127.0.0.1:8000/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: pass, role: 'supervisor' })
    });
    if(res.ok) {
       alert('Registro exitoso. Inicia sesión.');
       showSupRegister();
    } else {
       const data = await res.json();
       alert(data.detail || 'Error al registrar');
    }
  } catch(e) { alert('Error de conexión'); }
}
'''
        content = re.sub(r'function doLogin\(\) \{.*?(?=function doLogout)', js_login + '\n\n', content, flags=re.DOTALL)
        
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(content)

update_auth('operario.html', True)
update_auth('supervisor.html', False)
