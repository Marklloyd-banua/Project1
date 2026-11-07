import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { Integration } from '../../types/models'
export const integrationsApi=createResourceApi<Integration>(endpoints.integrations)
export const webhooksApi=createResourceApi<Integration>(endpoints.webhooks)
