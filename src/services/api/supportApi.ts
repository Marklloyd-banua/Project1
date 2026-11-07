import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { SupportTicket } from '../../types/models'
export const supportApi=createResourceApi<SupportTicket>(endpoints.support)
