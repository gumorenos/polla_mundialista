import { useAuthStatus } from '../api/hooks'

export function useAuth() {
  return useAuthStatus()
}
