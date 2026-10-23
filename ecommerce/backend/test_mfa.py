"""
test_mfa.py — Suite completa de pruebas automatizadas para MFA (TOTP)
Verifica:
  1. Login paso 1 -> mfa_required=True, stage="setup"
  2. Aislamiento: mfa_token no da acceso a endpoints de la API (401)
  3. Setup: entrega de secreto, QR SVG, URI y 10 recovery codes
  4. Activación con código inválido -> rechazo (400)
  5. Activación con código válido -> mfa_enabled=True, entrega access_token
  6. Login paso 1 con MFA activado -> stage="verify"
  7. Verificación con código inválido -> rechazo (401)
  8. Verificación con código TOTP válido -> entrega access_token
  9. Anti-reutilización (replay attack): rechazo del mismo código usado (401)
  10. Recuperación: código de emergencia válido -> éxito (200) y consumo del código
  11. Reutilización de código de emergencia ya consumido -> rechazo (401)
  12. Protección contra fuerza bruta: 5 intentos fallidos -> bloqueo temporal (423)
  13. Restablecimiento administrativo de MFA -> usuario puede volver a enrolarse
"""

import sys
import os
import pyotp
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# Configurar path
cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, cur_dir)

from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password
from app.core import mfa

client = TestClient(app)

TEST_USER_EMAIL = "mfa_test_user@smartwms.com"
TEST_USER_PASS  = "mfaPass123!"

def setup_test_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=TEST_USER_EMAIL).first()
        if not user:
            user = User(
                email=TEST_USER_EMAIL,
                full_name="Usuario Test MFA",
                hashed_password=hash_password(TEST_USER_PASS),
                role="operario",
                is_active=True,
            )
            db.add(user)
        else:
            user.is_active = True
            user.hashed_password = hash_password(TEST_USER_PASS)
            mfa.reset_user_mfa(user)
        db.commit()
    finally:
        db.close()


def run_all_mfa_tests():
    print("\n" + "=" * 65)
    print(" INICIANDO PRUEBAS AUTOMATIZADAS DE AUTENTICACIÓN MULTIFACTOR")
    print("=" * 65)

    setup_test_user()

    # 1. Login inicial (espera stage="setup")
    r_login1 = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    assert r_login1.status_code == 200, f"Error en login: {r_login1.text}"
    data1 = r_login1.json()
    assert data1["mfa_required"] is True, "mfa_required debe ser True"
    assert data1["stage"] == "setup", f"Esperaba stage 'setup', obtuvo {data1.get('stage')}"
    assert data1["access_token"] is None, "access_token no debe entregarse todavía"
    mfa_token = data1["mfa_token"]
    assert mfa_token, "mfa_token debe existir"
    print("  [OK] 1. Login paso 1: credenciales válidas -> MFA requerido (stage='setup').")

    # 2. Seguridad: el mfa_token no debe servir para llamar endpoints protegidos
    r_protected = client.get("/api/v1/inventory", headers={"Authorization": f"Bearer {mfa_token}"})
    assert r_protected.status_code == 401, f"El mfa_token dio acceso indebido: {r_protected.status_code}"
    print("  [OK] 2. Seguridad: token temporal 'mfa_pending' no da acceso a la API (401).")

    # 3. Setup de MFA
    r_setup = client.post("/api/auth/mfa/setup", headers={"Authorization": f"Bearer {mfa_token}"})
    assert r_setup.status_code == 200, f"Error en setup: {r_setup.text}"
    setup_data = r_setup.json()
    secret = setup_data["secret"]
    recovery_codes = setup_data["recovery_codes"]
    assert len(secret) == 32, "El secreto TOTP debe tener longitud de 32 caracteres (base32)"
    assert len(recovery_codes) == 10, "Deben generarse exactamente 10 códigos de recuperación"
    assert setup_data["qr_code_svg"].startswith("data:image/svg+xml"), "QR debe ser formato SVG data URI"
    print("  [OK] 3. Setup: secreto TOTP, QR SVG local y 10 códigos generados correctamente.")

    # 4. Activación con código inválido
    r_act_bad = client.post(
        "/api/auth/mfa/activate",
        json={"code": "000000", "mfa_token": mfa_token}
    )
    assert r_act_bad.status_code == 400, "Código inválido fue aceptado"
    print("  [OK] 4. Activación: código inválido rechazado con HTTP 400.")

    # 5. Activación con código válido generado por TOTP local
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()
    r_act_ok = client.post(
        "/api/auth/mfa/activate",
        json={"code": valid_code, "mfa_token": mfa_token}
    )
    assert r_act_ok.status_code == 200, f"Error en activación válida: {r_act_ok.text}"
    act_data = r_act_ok.json()
    final_token = act_data["access_token"]
    assert final_token, "Debe entregarse el access_token definitivo"
    assert act_data["mfa_required"] is False
    print("  [OK] 5. Activación: código TOTP válido aceptado, MFA activado y JWT final emitido.")

    # 5.1 Verificar que el token final sí da acceso a endpoints protegidos
    r_prot_ok = client.get("/api/auth/me", headers={"Authorization": f"Bearer {final_token}"})
    assert r_prot_ok.status_code == 200, "Token final no dio acceso a /api/auth/me"
    assert r_prot_ok.json()["mfa_enabled"] is True, "Usuario debe figurar con mfa_enabled=True"
    print("  [OK] 5.1 Verificación de sesión: access_token permite consultar perfil (mfa_enabled=True).")

    # 6. Nuevo login con usuario que ya tiene MFA activado (espera stage="verify")
    r_login2 = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    assert r_login2.status_code == 200
    data2 = r_login2.json()
    assert data2["stage"] == "verify", "Debe requerir stage 'verify'"
    verify_mfa_token = data2["mfa_token"]
    print("  [OK] 6. Login paso 1 de usuario enrolado -> MFA requerido (stage='verify').")

    # 7. Verificación con código erróneo
    r_ver_bad = client.post("/api/auth/mfa/verify", json={"code": "999999", "mfa_token": verify_mfa_token})
    assert r_ver_bad.status_code == 401, "Código incorrecto fue aceptado"
    print("  [OK] 7. Verificación: código incorrecto rechazado con HTTP 401.")

    # 8. Verificación con código correcto (siguiente time step válido dentro de la ventana de tolerancia)
    import time
    valid_code2 = totp.at(int(time.time()) + 30)
    r_ver_ok = client.post("/api/auth/mfa/verify", json={"code": valid_code2, "mfa_token": verify_mfa_token})
    assert r_ver_ok.status_code == 200, f"Error en verify: {r_ver_ok.text}"
    assert r_ver_ok.json()["access_token"], "access_token no entregado tras verify"
    print("  [OK] 8. Verificación: código TOTP válido aceptado y sesión iniciada.")

    # 9. Anti-reutilización (replay attack): reintentar inmediatamente con el mismo código valid_code2
    r_replay_login = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    replay_token = r_replay_login.json()["mfa_token"]
    r_replay = client.post("/api/auth/mfa/verify", json={"code": valid_code2, "mfa_token": replay_token})
    assert r_replay.status_code == 401, "Código TOTP reutilizado fue indebidamente aceptado"
    print("  [OK] 9. Anti-reutilización: rechazo de repetición del mismo código TOTP (replay attack).")


    # 10. Acceso de emergencia con código de recuperación
    rec_code = recovery_codes[0]
    r_rec_login = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    rec_mfa_token = r_rec_login.json()["mfa_token"]
    r_rec = client.post("/api/auth/mfa/recover", json={"recovery_code": rec_code, "mfa_token": rec_mfa_token})
    assert r_rec.status_code == 200, f"Error al usar código de recuperación: {r_rec.text}"
    assert r_rec.json()["access_token"], "access_token no emitido tras recuperación"
    print("  [OK] 10. Recuperación: acceso concedido con código de emergencia válido.")

    # 11. Intentar reutilizar el mismo código de recuperación
    r_rec_login2 = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    rec_mfa_token2 = r_rec_login2.json()["mfa_token"]
    r_rec_reuse = client.post("/api/auth/mfa/recover", json={"recovery_code": rec_code, "mfa_token": rec_mfa_token2})
    assert r_rec_reuse.status_code == 401, "Código de recuperación reutilizado fue aceptado"
    print("  [OK] 11. Recuperación: código de emergencia ya consumido rechazado (un solo uso).")

    # 12. Prueba de fuerza bruta / lockout temporal (5 intentos fallidos consecutivos)
    print("  [*] 12. Probando protección contra fuerza bruta (5 intentos fallidos)...")
    for attempt in range(4):
        client.post("/api/auth/mfa/verify", json={"code": f"11111{attempt}", "mfa_token": rec_mfa_token2})

    # El 5to intento debe disparar el bloqueo
    r_5th = client.post("/api/auth/mfa/verify", json={"code": "111115", "mfa_token": rec_mfa_token2})
    assert r_5th.status_code == 423, f"Se esperaba HTTP 423 Locked en el 5to intento, se obtuvo {r_5th.status_code}"
    # Cualquier intento subsiguiente de login debe ser rechazado inmediatamente con 423
    r_locked_login = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    assert r_locked_login.status_code == 423, "Cuenta bloqueada debe responder con HTTP 423"
    print("  [OK] 12. Seguridad contra fuerza bruta: cuenta bloqueada temporalmente tras 5 fallos (HTTP 423).")

    # 13. Restablecimiento administrativo de MFA
    db = SessionLocal()
    u = db.query(User).filter_by(email=TEST_USER_EMAIL).first()
    mfa.reset_user_mfa(u)
    db.commit()
    db.close()

    r_after_reset = client.post("/api/auth/login", data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASS})
    assert r_after_reset.status_code == 200
    assert r_after_reset.json()["stage"] == "setup", "Tras reset de MFA debe volver a solicitar enrolamiento inicial"
    print("  [OK] 13. Restablecimiento: el usuario vuelve al estado inicial de vinculación.")

    print("\n" + "=" * 65)
    print(" TODAS LAS PRUEBAS DE AUTENTICACIÓN MULTIFACTOR (MFA) PASARON EXITOSAMENTE")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_all_mfa_tests()
