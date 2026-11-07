import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { Role } from '../../types/models'
export const rolesApi={...createResourceApi<Role>(endpoints.roles),permissions:()=>import('./http').then(({request})=>request(endpoints.permissions))}
