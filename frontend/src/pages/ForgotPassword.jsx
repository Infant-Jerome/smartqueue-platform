import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { KeyRound, MailCheck, LockKeyhole, CheckCircle2, ArrowLeft } from 'lucide-react';
import api from '../services/api';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';
import Field from '../components/ui/Field';
import Input from '../components/ui/Input';
import PageHeader from '../components/ui/PageHeader';

const OTP_EXPIRY_SECONDS = 10 * 60;
const RESEND_COOLDOWN_SECONDS = 60;

function formatClock(total) {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [step, setStep] = useState('email'); // email | otp | password | done
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [resetToken, setResetToken] = useState(null); // memory only, never persisted
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [loading, setLoading] = useState(false);
  const [otpLeft, setOtpLeft] = useState(OTP_EXPIRY_SECONDS);
  const [resendLeft, setResendLeft] = useState(0);

  useEffect(() => {
    if (step !== 'otp') return;
    if (otpLeft <= 0 && resendLeft <= 0) return;
    const t = setTimeout(() => {
      if (otpLeft > 0) setOtpLeft((v) => v - 1);
      if (resendLeft > 0) setResendLeft((v) => v - 1);
    }, 1000);
    return () => clearTimeout(t);
  }, [step, otpLeft, resendLeft]);

  const sendOtp = async (e) => {
    if (e) e.preventDefault();
    setError('');
    setInfo('');
    if (!email.trim()) {
      setError('Please enter your email address.');
      return;
    }
    setLoading(true);
    try {
      await api.post('/auth/forgot-password', { email: email.trim() });
      // Generic reply by design; never reveals whether the email exists.
      setInfo('If an account exists for this email, a verification code has been sent.');
      setOtpLeft(OTP_EXPIRY_SECONDS);
      setResendLeft(RESEND_COOLDOWN_SECONDS);
      setStep('otp');
    } catch (err) {
      setError(err.message || 'Could not send the code. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const verifyOtp = async (e) => {
    e.preventDefault();
    setError('');
    setInfo('');
    if (otp.trim().length !== 6) {
      setError('Please enter the 6-digit code.');
      return;
    }
    setLoading(true);
    try {
      const res = await api.post('/auth/verify-reset-otp', { email: email.trim(), otp: otp.trim() });
      setResetToken(res.data?.reset_token || null);
      setStep('password');
    } catch (err) {
      setError(err.message || 'Verification failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const resetPassword = async (e) => {
    e.preventDefault();
    setError('');
    setInfo('');
    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (!resetToken) {
      setError('Session expired. Please request a new code.');
      setStep('email');
      return;
    }
    setLoading(true);
    try {
      await api.post('/auth/reset-password', {
        reset_token: resetToken,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      // Drop sensitive state immediately.
      setResetToken(null);
      setNewPassword('');
      setConfirmPassword('');
      setOtp('');
      setStep('done');
    } catch (err) {
      setError(err.message || 'Password reset failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--sq-background)]">
      <div className="max-w-md mx-auto px-4 py-8">
        <button
          type="button"
          onClick={() => navigate('/login')}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--sq-text-muted)] hover:text-[var(--sq-primary)] mb-4"
        >
          <ArrowLeft size={16} aria-hidden="true" /> Back to Login
        </button>

        {step === 'email' && (
          <>
            <PageHeader
              title="Forgot your password?"
              description="Enter your registered email and we'll send you a verification code."
              icon={<KeyRound size={20} aria-hidden="true" />}
            />
            <Card>
              {error && <p className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{error}</p>}
              <form onSubmit={sendOtp} className="space-y-4">
                <Field label="Email" required>
                  <Input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                  />
                </Field>
                <Button type="submit" fullWidth loading={loading}>
                  Send OTP
                </Button>
              </form>
            </Card>
          </>
        )}

        {step === 'otp' && (
          <>
            <PageHeader
              title="Verify your email"
              description={`Enter the 6-digit verification code sent to ${email}.`}
              icon={<MailCheck size={20} aria-hidden="true" />}
            />
            <Card>
              {error && <p className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{error}</p>}
              {info && <p className="mb-4 p-3 bg-[var(--sq-info-soft)] border border-[var(--sq-border)] rounded-[var(--sq-radius-lg)] text-[var(--sq-info)] text-sm">{info}</p>}
              <form onSubmit={verifyOtp} className="space-y-4">
                <Field
                  label="Verification code"
                  required
                  hint={otpLeft > 0 ? `Code expires in ${formatClock(otpLeft)}` : 'Code expired — request a new one below.'}
                >
                  <Input
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="123456"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    required
                  />
                </Field>
                <Button type="submit" fullWidth loading={loading} disabled={otpLeft <= 0}>
                  Verify OTP
                </Button>
                <Button
                  type="button"
                  tone="secondary"
                  fullWidth
                  loading={false}
                  disabled={loading || resendLeft > 0}
                  onClick={sendOtp}
                >
                  {resendLeft > 0 ? `Resend OTP in ${resendLeft}s` : 'Resend OTP'}
                </Button>
              </form>
            </Card>
          </>
        )}

        {step === 'password' && (
          <>
            <PageHeader
              title="Create a new password"
              description="Choose a strong password (at least 6 characters)."
              icon={<LockKeyhole size={20} aria-hidden="true" />}
            />
            <Card>
              {error && <p className="mb-4 p-3 bg-[var(--sq-danger-soft)] border border-[#fca5a5] rounded-[var(--sq-radius-lg)] text-[var(--sq-danger)] text-sm" role="alert">{error}</p>}
              <form onSubmit={resetPassword} className="space-y-4">
                <Field label="New password" required>
                  <Input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Enter new password"
                    autoComplete="new-password"
                    required
                  />
                </Field>
                <Field label="Confirm password" required>
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    autoComplete="new-password"
                    required
                  />
                </Field>
                <Button type="submit" fullWidth loading={loading}>
                  Reset Password
                </Button>
              </form>
            </Card>
          </>
        )}

        {step === 'done' && (
          <Card padding="lg" className="text-center">
            <span className="mx-auto flex w-12 h-12 rounded-full bg-[var(--sq-success-soft)] text-[var(--sq-success)] items-center justify-center" aria-hidden="true">
              <CheckCircle2 size={24} />
            </span>
            <h1 className="sq-h1 text-[var(--sq-text)] mt-4">Password reset successfully</h1>
            <p className="text-sm text-[var(--sq-text-muted)] mt-2">Your password has been updated.</p>
            <Link to="/login" className="block mt-6">
              <Button fullWidth>Back to Login</Button>
            </Link>
          </Card>
        )}
      </div>
    </div>
  );
}
