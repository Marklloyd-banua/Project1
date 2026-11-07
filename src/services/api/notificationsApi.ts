import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import { request } from './http'
import type { ApiResponse,Notification } from '../../types/models'
export const notificationsApi={...createResourceApi<Notification>(endpoints.notifications),send:(id:string)=>request<ApiResponse<Notification>>(`${endpoints.notifications}/${encodeURIComponent(id)}/send`,{method:'POST'})}
