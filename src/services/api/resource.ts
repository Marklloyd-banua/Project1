import { request } from './http'
import type { ApiResponse,BaseRecord,FilterParams,PaginatedResponse } from '../../types/models'
export function createResourceApi<T extends BaseRecord>(endpoint:string){return {
 list:(params:FilterParams={})=>{const query=new URLSearchParams();Object.entries(params).forEach(([key,value])=>{if(value!==undefined)query.set(key,String(value))});return request<PaginatedResponse<T>>(`${endpoint}${query.size?`?${query.toString()}`:''}`)},
 get:(id:string)=>request<ApiResponse<T>>(`${endpoint}/${encodeURIComponent(id)}`),
 create:(payload:Partial<T>)=>request<ApiResponse<T>>(endpoint,{method:'POST',body:JSON.stringify(payload)}),
 update:(id:string,payload:Partial<T>)=>request<ApiResponse<T>>(`${endpoint}/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify(payload)}),
 remove:(id:string)=>request<void>(`${endpoint}/${encodeURIComponent(id)}`,{method:'DELETE'}),
}}
