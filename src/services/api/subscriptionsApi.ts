import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import { request } from './http'
import type { ApiResponse,Subscription } from '../../types/models'
export const subscriptionsApi={...createResourceApi<Subscription>(endpoints.subscriptions),cancel:(id:string)=>request<ApiResponse<Subscription>>(`${endpoints.subscriptions}/${encodeURIComponent(id)}/cancel`,{method:'POST'}),reactivate:(id:string)=>request<ApiResponse<Subscription>>(`${endpoints.subscriptions}/${encodeURIComponent(id)}/reactivate`,{method:'POST'})}
