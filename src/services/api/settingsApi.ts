import { request } from './http'
import { endpoints } from './endpoints'
import type { ApiResponse,PlatformSettings } from '../../types/models'
export const settingsApi={get:()=>request<ApiResponse<PlatformSettings>>(endpoints.settings),update:(payload:Partial<PlatformSettings>)=>request<ApiResponse<PlatformSettings>>(endpoints.settings,{method:'PATCH',body:JSON.stringify(payload)})}
