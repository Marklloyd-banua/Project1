import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { Store } from '../../types/models'
export const storesApi=createResourceApi<Store>(endpoints.stores)
