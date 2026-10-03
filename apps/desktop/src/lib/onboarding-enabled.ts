export function isOnboardingEnabled(): boolean {
  return window.slaveDesktop?.guestOnboardingEnabled === true
}
