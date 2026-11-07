import { createResourceApi } from './resource'
import { endpoints } from './endpoints'
import type { AuditLog } from '../../types/models'
export const auditLogsApi=createResourceApi<AuditLog>(endpoints.auditLogs)
