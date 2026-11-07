import { endpoints } from './api/endpoints'
import { request } from './api/http'
import { listRecords,removeRecord,saveRecord,updateStatus } from './mock/repository'
import type { BaseRecord,PaginatedResponse } from '../types/models'
const resources:Record<string,string>={stores:endpoints.stores,tenants:endpoints.tenants,'platform-users':endpoints.users,roles:endpoints.roles,plans:endpoints.plans,subscriptions:endpoints.subscriptions,billing:endpoints.invoices,payments:endpoints.payments,promotions:endpoints.promotions,monitoring:'/monitoring/incidents','audit-logs':endpoints.auditLogs,notifications:endpoints.notifications,integrations:endpoints.integrations,settings:endpoints.settings,security:endpoints.sessions,support:endpoints.support}
const useMock=import.meta.env.VITE_USE_MOCK_API==='true'
function endpoint(resource:string){return resources[resource]??`/${resource}`}
export async function listPlatformRecords(resource:string,query='',status='All',page=1,pageSize=8,sortBy='',sortDirection:'asc'|'desc'='asc'):Promise<PaginatedResponse<BaseRecord>>{
 if(useMock)return listRecords(resource,query,status,page,pageSize,sortBy,sortDirection)
 const params=new URLSearchParams({page:String(page),pageSize:String(pageSize)});if(query)params.set('search',query);if(status!=='All')params.set('status',status);if(sortBy)params.set('sortBy',sortBy);params.set('sortDirection',sortDirection)
 return request<PaginatedResponse<BaseRecord>>(`${endpoint(resource)}?${params.toString()}`)
}
export async function savePlatformRecord(resource:string,value:Partial<BaseRecord>,id?:string):Promise<BaseRecord>{
 if(useMock)return saveRecord(resource,value,id)
 const path=id?`${endpoint(resource)}/${encodeURIComponent(id)}`:endpoint(resource);const response=await request<{data:BaseRecord}>(path,{method:id?'PATCH':'POST',body:JSON.stringify(value)});return response.data
}
export async function deletePlatformRecord(resource:string,id:string):Promise<void>{if(useMock)return removeRecord(resource,id);return request<void>(`${endpoint(resource)}/${encodeURIComponent(id)}`,{method:'DELETE'})}
export async function setPlatformRecordStatus(resource:string,id:string,status:BaseRecord['status']):Promise<void>{if(useMock)return updateStatus(resource,id,status);if(!['stores','tenants'].includes(resource))throw {message:`Status changes are not configured for ${resource}.`,code:'UNSUPPORTED_ACTION'};return request<void>(`${endpoint(resource)}/${encodeURIComponent(id)}/status`,{method:'PATCH',body:JSON.stringify({status})})}
