import { getSeedData } from '../../data/mockData'
import type { BaseRecord, PaginatedResponse } from '../../types/models'
const key=(resource:string)=>`saas-admin-demo:${resource}`
const wait=(ms=180)=>new Promise(resolve=>setTimeout(resolve,ms))
function readRows(resource:string):BaseRecord[]{
 try{
  const stored=localStorage.getItem(key(resource))
  if(!stored)return getSeedData(resource)
  const parsed:unknown=JSON.parse(stored)
  if(Array.isArray(parsed)&&parsed.every((row)=>row&&typeof row==='object'&&typeof row.id==='string'&&typeof row.status==='string'&&typeof row.createdAt==='string'))return parsed as BaseRecord[]
 }catch{ /* Use the fixtures when browser storage is unavailable or invalid. */ }
 return getSeedData(resource)
}
export async function listRecords(resource:string, query='', status='All', page=1, pageSize=8, sortBy='', sortDirection:'asc'|'desc'='asc'):Promise<PaginatedResponse<BaseRecord>>{
 await wait()
 let rows=readRows(resource)
 if(query) rows=rows.filter(row=>Object.values(row).some(value=>String(value).toLowerCase().includes(query.toLowerCase())))
 if(status!=='All') rows=rows.filter(row=>row.status===status)
 if(sortBy) rows.sort((left,right)=>String(left[sortBy]??'').localeCompare(String(right[sortBy]??''),undefined,{numeric:true,sensitivity:'base'})*(sortDirection==='asc'?1:-1))
 return {items:rows.slice((page-1)*pageSize,page*pageSize),page,pageSize,total:rows.length}
}
export async function saveRecord(resource:string, value:Partial<BaseRecord>, id?:string):Promise<BaseRecord>{
 await wait(260); const rows=readRows(resource)
 const record:BaseRecord={id:id??`${resource.slice(0,3).toUpperCase()}-${Date.now().toString().slice(-5)}`,status:'Active',createdAt:new Date().toISOString().slice(0,10),...value} as BaseRecord
 const updated=id?rows.map(row=>row.id===id?{...row,...record}:row):[record,...rows]
 localStorage.setItem(key(resource),JSON.stringify(updated)); return record
}
export async function removeRecord(resource:string,id:string):Promise<void>{await wait();const rows=readRows(resource);localStorage.setItem(key(resource),JSON.stringify(rows.filter(row=>row.id!==id)))}
export async function updateStatus(resource:string,id:string,status:BaseRecord['status']):Promise<void>{const rows=readRows(resource);localStorage.setItem(key(resource),JSON.stringify(rows.map(row=>row.id===id?{...row,status}:row)))}
