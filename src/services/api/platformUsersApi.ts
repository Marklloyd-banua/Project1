import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { PlatformUser } from '../../types/models'
export const platformUsersApi=createResourceApi<PlatformUser>(endpoints.users)
