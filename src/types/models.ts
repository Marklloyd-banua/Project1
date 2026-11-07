export type EntityStatus = 'Active' | 'Trial' | 'Past due' | 'Suspended' | 'Cancelled' | 'Draft' | 'Paid' | 'Failed' | 'Pending' | 'Open' | 'Resolved'
export interface BaseRecord { id: string; status: EntityStatus; createdAt: string; [key: string]: string | number | boolean | EntityStatus }
export interface Store extends BaseRecord { name: string; owner: string; domain: string; plan: string; mrr: number; products: number }
export interface Tenant extends BaseRecord { name: string; email: string; stores: number; plan: string }
export interface PlatformUser extends BaseRecord { name: string; email: string; role: string; lastLogin: string }
export interface Role extends BaseRecord { name: string; users: number; permissions: number }
export interface SubscriptionPlan extends BaseRecord { name: string; monthly: number; annual: number; stores: number; products: number }
export interface Subscription extends BaseRecord { tenant: string; store: string; plan: string; cycle: string; nextBilling: string; amount: number }
export interface Invoice extends BaseRecord { tenant: string; number: string; amount: number; dueDate: string }
export interface Payment extends BaseRecord { tenant: string; invoice: string; gateway: string; amount: number; date: string }
export interface Promotion extends BaseRecord { name: string; code: string; discount: string; redemptions: number; expires: string }
export interface AuditLog extends BaseRecord { user: string; action: string; resource: string; ip: string }
export interface Notification extends BaseRecord { title: string; type: string; audience: string; sent: string }
export interface Integration extends BaseRecord { name: string; category: string; usage: string; lastSync: string }
export interface SupportTicket extends BaseRecord { subject: string; tenant: string; priority: string; assignee: string }
export interface Permission { resource: string; read: boolean; create: boolean; update: boolean; delete: boolean }
export interface Webhook extends BaseRecord { endpoint: string; events: string; lastDelivery: string }
export interface SystemMetric { label: string; value: string; change: string }
export interface PlatformSettings { platformName: string; currency: string; timezone: string; language: string; maintenanceMode: boolean }
export interface ApiResponse<T> { data: T; message?: string }
export interface ApiError { message: string; code?: string; details?: Record<string, string> }
export interface PaginatedResponse<T> { items: T[]; page: number; pageSize: number; total: number }
export interface PaginationParams { page?: number; pageSize?: number }
export interface SortParams { sortBy?: string; sortDirection?: 'asc' | 'desc' }
export type FilterParams = Record<string, string | number | boolean | undefined>
