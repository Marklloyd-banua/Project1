import { request } from './http'
import { endpoints } from './endpoints'
import type { ApiResponse,FilterParams } from '../../types/models'
export const platformApi={overview:()=>request<ApiResponse<Record<string,unknown>>>(endpoints.overview),analytics:(params:FilterParams={})=>request<ApiResponse<Record<string,unknown>>>(`${endpoints.analytics}?${new URLSearchParams(Object.entries(params).filter(([,v])=>v!==undefined).map(([k,v])=>[k,String(v)]))}`),health:()=>request<ApiResponse<Record<string,unknown>>>(endpoints.health)}
