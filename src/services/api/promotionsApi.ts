import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { Promotion } from '../../types/models'
export const promotionsApi=createResourceApi<Promotion>(endpoints.promotions)
