// features/auth/login/login.component.ts
// Componente de login con soporte para Autenticación Multifactor (TOTP), QR y recuperación

import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormControl, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';

// Angular Material
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AuthService, MFASetupResponse } from '../../../core/services/auth.service';

export type AuthStep = 'credentials' | 'mfa-verify' | 'mfa-setup' | 'mfa-recover';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss'],
})
export class LoginComponent implements OnInit {
  loginForm!: FormGroup;
  mfaCodeControl = new FormControl('', [
    Validators.required,
    Validators.minLength(6),
    Validators.maxLength(6),
    Validators.pattern(/^\d{6}$/),
  ]);
  recoveryCodeControl = new FormControl('', [
    Validators.required,
    Validators.minLength(10),
    Validators.maxLength(12),
  ]);

  step = signal<AuthStep>('credentials');
  isLoading = signal(false);
  hidePassword = signal(true);
  mfaToken = signal<string | null>(null);
  userRole = signal<string | null>(null);

  // Datos para el paso de setup (vinculación)
  setupData = signal<MFASetupResponse | null>(null);
  qrSafeUrl = signal<SafeUrl | null>(null);
  copiedSecret = signal(false);
  copiedCodes = signal(false);

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    if (this.authService.isAuthenticated()) {
      this.router.navigate(['/dashboard']);
      return;
    }

    this.loginForm = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(6)]],
    });
  }

  // ─── Paso 1: Envío de credenciales ─────────────────────────────────────────

  onSubmitCredentials(): void {
    if (this.loginForm.invalid || this.isLoading()) return;

    this.isLoading.set(true);

    this.authService.login(this.loginForm.value).subscribe({
      next: (res) => {
        this.isLoading.set(false);
        if (res.mfa_required && res.mfa_token) {
          this.mfaToken.set(res.mfa_token);
          this.userRole.set(res.role);

          if (res.stage === 'setup') {
            this.startMfaSetup(res.mfa_token);
          } else {
            this.step.set('mfa-verify');
            this.mfaCodeControl.reset();
          }
        } else {
          // Acceso directo (sin MFA)
          this.router.navigate(['/dashboard']);
        }
      },
      error: (err) => {
        this.isLoading.set(false);
        let message = 'Error de conexión. Intenta nuevamente.';
        if (err.status === 401) {
          message = 'Credenciales incorrectas. Verifica tu email y contraseña.';
        } else if (err.status === 403) {
          message = 'Cuenta desactivada. Contacta al supervisor.';
        } else if (err.status === 423) {
          message = err.error?.detail || 'Cuenta bloqueada temporalmente por intentos fallidos.';
        }
        this.snackBar.open(message, 'Cerrar', { duration: 5000, panelClass: ['error-snack'] });
      },
    });
  }

  // ─── Paso 2A: Verificar código TOTP ────────────────────────────────────────

  onSubmitVerify(): void {
    const token = this.mfaToken();
    const code = this.mfaCodeControl.value;
    if (!token || !code || this.mfaCodeControl.invalid || this.isLoading()) return;

    this.isLoading.set(true);

    this.authService.mfaVerify(code, token).subscribe({
      next: () => {
        this.isLoading.set(false);
        this.snackBar.open('¡Autenticación exitosa!', 'OK', { duration: 2500 });
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        this.isLoading.set(false);
        let msg = 'Código de autenticación incorrecto o expirado.';
        if (err.status === 423) {
          msg = err.error?.detail || 'Cuenta bloqueada temporalmente por demasiados intentos.';
        }
        this.snackBar.open(msg, 'Cerrar', { duration: 5000, panelClass: ['error-snack'] });
      },
    });
  }

  // ─── Paso 2B: Enrolamiento / Setup inicial ──────────────────────────────────

  private startMfaSetup(token: string): void {
    this.isLoading.set(true);
    this.authService.mfaSetup(token).subscribe({
      next: (setupRes) => {
        this.isLoading.set(false);
        this.setupData.set(setupRes);
        this.qrSafeUrl.set(this.sanitizer.bypassSecurityTrustUrl(setupRes.qr_code_svg));
        this.step.set('mfa-setup');
        this.mfaCodeControl.reset();
      },
      error: () => {
        this.isLoading.set(false);
        this.snackBar.open('Error al generar clave de autenticador. Intenta de nuevo.', 'Cerrar', {
          duration: 4000,
        });
        this.step.set('credentials');
      },
    });
  }

  onSubmitActivate(): void {
    const token = this.mfaToken();
    const code = this.mfaCodeControl.value;
    if (!token || !code || this.mfaCodeControl.invalid || this.isLoading()) return;

    this.isLoading.set(true);

    this.authService.mfaActivate(code, token).subscribe({
      next: () => {
        this.isLoading.set(false);
        this.snackBar.open('¡Autenticador vinculado con éxito! Bienvenido.', 'OK', { duration: 3000 });
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        this.isLoading.set(false);
        const msg = err.error?.detail || 'Código incorrecto. Verifica la hora de tu teléfono.';
        this.snackBar.open(msg, 'Cerrar', { duration: 5000, panelClass: ['error-snack'] });
      },
    });
  }

  // ─── Paso 2C: Recuperación de emergencia ───────────────────────────────────

  onSubmitRecover(): void {
    const token = this.mfaToken();
    const recCode = this.recoveryCodeControl.value;
    if (!token || !recCode || this.recoveryCodeControl.invalid || this.isLoading()) return;

    this.isLoading.set(true);

    this.authService.mfaRecover(recCode, token).subscribe({
      next: () => {
        this.isLoading.set(false);
        this.snackBar.open('Acceso de emergencia concedido.', 'OK', { duration: 3000 });
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        this.isLoading.set(false);
        const msg = err.error?.detail || 'Código de recuperación inválido o ya utilizado.';
        this.snackBar.open(msg, 'Cerrar', { duration: 5000, panelClass: ['error-snack'] });
      },
    });
  }

  // ─── Utilidades de UI ──────────────────────────────────────────────────────

  copySecret(): void {
    const secret = this.setupData()?.secret;
    if (!secret) return;
    navigator.clipboard.writeText(secret).then(() => {
      this.copiedSecret.set(true);
      setTimeout(() => this.copiedSecret.set(false), 2500);
    });
  }

  copyRecoveryCodes(): void {
    const codes = this.setupData()?.recovery_codes;
    if (!codes) return;
    const text = 'SMARTWMS - CÓDIGOS DE RECUPERACIÓN MFA:\n' + codes.join('\n');
    navigator.clipboard.writeText(text).then(() => {
      this.copiedCodes.set(true);
      setTimeout(() => this.copiedCodes.set(false), 2500);
      this.snackBar.open('Códigos copiados. Guárdalos en un lugar seguro.', 'OK', { duration: 3000 });
    });
  }

  backToCredentials(): void {
    this.step.set('credentials');
    this.mfaToken.set(null);
    this.setupData.set(null);
  }

  togglePassword(): void {
    this.hidePassword.update((v) => !v);
  }

  get emailControl() { return this.loginForm.get('email')!; }
  get passwordControl() { return this.loginForm.get('password')!; }
}
