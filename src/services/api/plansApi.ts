import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { SubscriptionPlan } from '../../types/models'
export const plansApi=createResourceApi<SubscriptionPlan>(endpoints.plans)
