import { request } from './http'
import { endpoints } from './endpoints'
import type { ApiResponse } from '../../types/models'
export const monitoringApi={health:()=>request<ApiResponse<Record<string,unknown>>>(endpoints.monitoring),metrics:()=>request<ApiResponse<Record<string,unknown>>>('/monitoring/metrics'),incidents:()=>request<ApiResponse<Record<string,unknown>>>('/monitoring/incidents')}
