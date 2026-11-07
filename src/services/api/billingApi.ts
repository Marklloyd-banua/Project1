import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import { request } from './http'
import type { ApiResponse,Invoice } from '../../types/models'
export const billingApi={...createResourceApi<Invoice>(endpoints.invoices),send:(id:string)=>request<ApiResponse<Invoice>>(`${endpoints.invoices}/${encodeURIComponent(id)}/send`,{method:'POST'}),void:(id:string)=>request<ApiResponse<Invoice>>(`${endpoints.invoices}/${encodeURIComponent(id)}/void`,{method:'POST'})}
