# Backend Integration Requirements

## Authentication
Required endpoints:
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout

Request format:
```json
{
  "email": "string",
  "password": "string"
}
```

## Authorization
Required headers:
```
Authorization: Bearer <token>
```

## API Contracts
All responses must include:
- Standardized error format
- Proper HTTP status codes
- CORS headers when needed

## Security Requirements
- HTTPS mandatory for production
- HttpOnly cookies recommended for sessions
- CSRF protection required for state-changing requests
- Rate limiting recommended

## Data Flow
1. Client sends credentials to /auth/login
2. Server returns JWT with expiration
3. Client stores token in memory (NOT localStorage)
4. Token added to Authorization header
5. Client handles 401 errors with token refresh

## Example Protected Request
```javascript
GET /api/v1/users
Headers: {
  "Authorization": "Bearer eyJhbGci...",
  "Content-Type": "application/json"
}
```
