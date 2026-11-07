import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { Tenant } from '../../types/models'
export const tenantsApi=createResourceApi<Tenant>(endpoints.tenants)
