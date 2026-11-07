import { request } from './http'
import { endpoints } from './endpoints'
import type { ApiResponse,BaseRecord } from '../../types/models'
export const securityApi={sessions:()=>request<ApiResponse<BaseRecord[]>>(endpoints.sessions),revokeSession:(id:string)=>request<void>(`${endpoints.sessions}/${encodeURIComponent(id)}`,{method:'DELETE'}),events:()=>request<ApiResponse<BaseRecord[]>>(endpoints.securityEvents)}
