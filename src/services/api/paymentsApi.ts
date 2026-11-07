import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import { request } from './http'
import type { ApiResponse,Payment } from '../../types/models'
export const paymentsApi={...createResourceApi<Payment>(endpoints.payments),refund:(id:string,amount:number,reason:string)=>request<ApiResponse<Payment>>(`${endpoints.payments}/${encodeURIComponent(id)}/refunds`,{method:'POST',body:JSON.stringify({amount,reason})})}
