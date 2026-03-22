# Multi-User System Design (Simplified)

> **Design Philosophy**: This is a **local-first AI platform**, not a SaaS product.
> The authentication system should be simple, practical, and easy to maintain.

## 1. Current State Analysis

### 1.1 Existing Infrastructure

| Component | Status | Details |
|-----------|--------|---------|
| User ID Header | ✅ Exists | `X-User-Id` header with `default` fallback |
| User Context Middleware | ✅ Exists | `UserContextMiddleware` injects `user_id` into `request.state` |
| Data Models with `user_id` | ✅ Exists | Session, Message, KnowledgeBase, Document, MemoryItem |
| Access Control | ❌ Missing | No ownership validation |
| Authentication | ❌ Missing | No login/register mechanism |
| User Management | ❌ Missing | No user CRUD |

### 1.2 Current User ID Flow

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   HTTP Request  │────▶│  X-User-Id Header    │────▶│  DEFAULT_USER   │
│                 │     │  (if present)        │     │  (fallback)     │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │  UserContextMiddleware │
                    │  request.state.user_id │
                    └──────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │  Business Logic      │
                    │  (user_id filtering) │
                    └──────────────────────┘
```

---

## 2. Design Goals

### 2.1 Core Requirements

1. **Authentication**: Secure login/logout mechanism
2. **User Management**: Registration, profile, password management
3. **Data Isolation**: Strict user data separation
4. **Simple Roles**: Admin vs Regular user (no complex RBAC)

### 2.2 Non-Goals (Out of Scope)

- Complex RBAC with granular permissions
- API key management (use JWT for programmatic access)
- Session tracking and revocation (JWT expiration suffices)
- Audit logging (optional for local deployment)
- OAuth/Social login
- Multi-tenant SaaS architecture
- Enterprise SSO integration

---

## 3. Architecture Design

### 3.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Frontend (Vue 3)                               │
├─────────────────────────────────────────────────────────────────────────┤
│  Login Page  │  Register Page  │  Profile Page  │  Settings              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐                                        │
│  │ Auth Router │  │ User Router │                                        │
│  │ /auth/*     │  │ /users/*    │                                        │
│  └─────────────┘  └─────────────┘                                        │
│         │                │                                              │
│         ▼                ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Auth Middleware Layer                         │   │
│  │  ┌─────────────┐  ┌─────────────┐                                │   │
│  │  │ JWT Verify  │  │ Role Check  │                                │   │
│  │  │ Middleware  │  │ Middleware  │                                │   │
│  │  └─────────────┘  └─────────────┘                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Service Layer                                 │   │
│  │  UserService │ AuthService                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Data Layer (SQLAlchemy)                       │   │
│  │  User (with role enum: admin | user)                             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Authentication Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client  │     │  Backend │     │  Service │     │ Database │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │                │
     │ POST /auth/login               │                │
     │ {email, password}              │                │
     │───────────────▶│                │                │
     │                │ verify_credentials             │
     │                │───────────────▶│                │
     │                │                │ SELECT user    │
     │                │                │───────────────▶│
     │                │                │◀───────────────│
     │                │                │ verify hash    │
     │                │◀───────────────│                │
     │                │ create JWT token               │
     │                │───────────────▶│                │
     │◀───────────────│                │                │
     │ {token, user}  │                │                │
     │                │                │                │
     │ Subsequent requests             │                │
     │ Authorization: Bearer <token>   │                │
     │───────────────▶│                │                │
     │                │ verify JWT     │                │
     │                │───────────────▶│                │
     │                │◀───────────────│                │
     │                │ inject user_id │                │
     │                │ into request   │                │
     │                │                │                │
```

---

## 4. Data Model Design

### 4.1 Simplified Schema

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              User                                       │
├─────────────────────────────────────────────────────────────────────────┤
│ id (PK)              - UUID, unique identifier                          │
│ email (unique)       - Login email, must be unique                      │
│ password_hash        - Bcrypt hashed password                           │
│ display_name         - User's display name                              │
│ avatar_url           - Optional avatar URL                              │
│ role                 - Enum: 'admin' | 'user'                           │
│ is_active            - Account active flag                              │
│ created_at           - Account creation timestamp                       │
│ updated_at           - Last update timestamp                            │
│ last_login_at        - Last successful login timestamp                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 SQLAlchemy Model

```python
# backend/core/data/models/user.py

import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, func, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from core.data.base import Base


class UserRole(str, enum.Enum):
    """User role enum - simple two-tier system"""
    ADMIN = "admin"
    USER = "user"


class User(Base):
    """User table - the only table needed for simplified auth"""
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), 
        nullable=False, 
        default=UserRole.USER
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(),
        onupdate=func.now()
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), 
        nullable=True
    )
    
    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
    
    def to_dict(self) -> dict:
        """Convert to dictionary (excludes password_hash)"""
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "role": self.role.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
```

### 4.3 Design Decisions

| Decision | Rationale |
|----------|-----------|
| Role as enum, not table | Simple two-tier system, no need for flexible RBAC |
| No separate Role/Permission tables | Overkill for local platform |
| No APIKey table | Use JWT for programmatic access |
| No UserSession table | JWT expiration handles session timeout |
| No AuditLog table | Optional, can be added later if needed |
| Single User table | Minimal complexity, easy to understand |

---

## 5. Role Design

### 5.1 Simple Two-Tier System

| Role | Description | Capabilities |
|------|-------------|-------------|
| `admin` | Administrator | Full system access, user management, model configuration |
| `user` | Regular user | Chat, knowledge base, memory (own data only) |

### 5.2 Role-Based Access Control

| Resource | admin | user |
|----------|-------|------|
| Chat (own) | ✅ | ✅ |
| Chat (others) | ✅ | ❌ |
| Knowledge Base (own) | ✅ | ✅ |
| Knowledge Base (others) | ✅ | ❌ |
| Memory (own) | ✅ | ✅ |
| Memory (others) | ✅ | ❌ |
| Model List | ✅ | ✅ |
| Model Configuration | ✅ | ❌ |
| User Management | ✅ | ❌ |
| System Settings | ✅ | ❌ |

### 5.3 Permission Check Implementation

```python
# backend/core/auth/permissions.py

def check_permission(user: User, resource_type: str, resource_owner_id: str = None) -> bool:
    """
    Simple permission check:
    - Admin: always allowed
    - User: only own resources
    """
    if user.role == UserRole.ADMIN:
        return True
    
    # Regular user can only access their own resources
    if resource_owner_id and resource_owner_id != user.id:
        return False
    
    return True


def require_admin(user: User) -> None:
    """Raise exception if user is not admin"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403, 
            detail="Admin access required"
        )
```

### 5.4 First User Setup

```python
# backend/core/auth/setup.py

async def initialize_system():
    """
    Initialize the system on first run.
    The first registered user becomes admin automatically.
    """
    user_count = await db.scalar(select(func.count()).select_from(User))
    
    if user_count == 0:
        # No users exist - first registration will be admin
        return {"first_user_becomes_admin": True}
    
    return {"first_user_becomes_admin": False}


async def register_user(email: str, password: str, display_name: str = None) -> User:
    """Register a new user. First user becomes admin."""
    user_count = await db.scalar(select(func.count()).select_from(User))
    
    role = UserRole.ADMIN if user_count == 0 else UserRole.USER
    
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or email.split("@")[0],
        role=role,
    )
    
    db.add(user)
    await db.commit()
    
    return user
```

---

## 6. API Design

### 6.1 Authentication Endpoints

```
POST   /api/v1/auth/register     - Register new user (first user becomes admin)
POST   /api/v1/auth/login        - Login (returns JWT)
POST   /api/v1/auth/logout       - Logout (client-side token removal)
POST   /api/v1/auth/password     - Change password
GET    /api/v1/auth/me           - Get current user info
GET    /api/v1/auth/status       - Check if system needs initial setup
```

### 6.2 User Management Endpoints

```
GET    /api/v1/users             - List users (admin only)
GET    /api/v1/users/:id         - Get user details (own or admin)
PUT    /api/v1/users/:id         - Update user (own or admin)
DELETE /api/v1/users/:id         - Delete user (admin only)
PUT    /api/v1/users/:id/role    - Change user role (admin only)
PUT    /api/v1/users/:id/activate - Activate/deactivate user (admin only)
```

### 6.3 Request/Response Examples

```python
# Register
POST /api/v1/auth/register
{
  "email": "user@example.com",
  "password": "securepassword",
  "display_name": "John Doe"
}

# Response
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "John Doe",
    "role": "user",
    "created_at": "2026-01-08T10:00:00Z"
  },
  "token": "eyJhbGciOiJIUzI1NiIs..."
}

# Login
POST /api/v1/auth/login
{
  "email": "user@example.com",
  "password": "securepassword"
}

# Response
{
  "user": { ... },
  "token": "eyJhbGciOiJIUzI1NiIs..."
}

# Get current user
GET /api/v1/auth/me
Authorization: Bearer <token>

# Response
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "John Doe",
  "role": "user",
  "is_active": true,
  "created_at": "2026-01-08T10:00:00Z",
  "last_login_at": "2026-01-08T12:00:00Z"
}
```

---

## 7. Security Considerations

### 7.1 Password Security

- Use `bcrypt` for password hashing (12 rounds)
- Minimum password length: 8 characters
- Store only password hash, never plain text

### 7.2 JWT Configuration

```python
# backend/config/settings.py

class AuthSettings:
    JWT_SECRET_KEY: str = "change-me-in-production"  # MUST be changed in production
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_HOURS: int = 24  # Token valid for 24 hours
    JWT_ISSUER: str = "local-ai-platform"
```

### 7.3 JWT Token Structure

```python
# Token payload
{
    "sub": "user-uuid",           # Subject (user ID)
    "email": "user@example.com",  # User email
    "role": "user",               # User role
    "exp": 1704326400,            # Expiration timestamp
    "iat": 1704240000,            # Issued at timestamp
    "iss": "local-ai-platform"    # Issuer
}
```

### 7.4 Authentication Middleware

```python
# backend/middleware/auth.py

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer(auto_error=False)

async def get_current_user(request: Request) -> User:
    """
    Get current user from JWT token.
    Falls back to X-User-Id header for backward compatibility.
    """
    # Try JWT token first
    token = await security(request)
    if token:
        payload = verify_jwt_token(token.credentials)
        user = await get_user_by_id(payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(401, "Invalid or inactive user")
        return user
    
    # Fallback to X-User-Id header (legacy, for migration)
    user_id = request.headers.get("X-User-Id")
    if user_id:
        user = await get_user_by_id(user_id)
        if user and user.is_active:
            return user
    
    raise HTTPException(401, "Authentication required")
```

### 7.5 CORS Configuration

```python
# backend/config/settings.py

ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Frontend dev server
    "http://localhost:3000",
]

ALLOW_CREDENTIALS = True
```

---

## 8. Migration Strategy

### 8.1 Phase 1: Database & Core Auth (Week 1)

1. Create `users` table with SQLAlchemy model
2. Implement password hashing utilities (bcrypt)
3. Implement JWT token generation and validation
4. Create auth service (register, login, verify)
5. Create auth router with basic endpoints

### 8.2 Phase 2: Middleware & Integration (Week 2)

1. Create JWT authentication middleware
2. Update existing endpoints to use JWT auth
3. Add user_id validation to existing data models
4. Implement first-user-becomes-admin logic
5. Test with existing frontend

### 8.3 Phase 3: User Management (Week 3)

1. Create user router (list, get, update, delete)
2. Implement role-based access control checks
3. Add admin-only endpoints
4. Update existing endpoints with ownership checks

### 8.4 Phase 4: Frontend Integration (Week 4)

1. Create auth store (Pinia)
2. Create login page
3. Create register page
4. Implement protected routes
5. Add auth token to API client
6. Create user profile page

### 8.5 Backward Compatibility

During migration, maintain backward compatibility:

```python
# backend/middleware/auth.py

async def get_user_id(request: Request) -> str:
    """
    Get user ID from:
    1. JWT token (preferred)
    2. X-User-Id header (legacy, for migration)
    """
    # Try JWT first
    token = extract_jwt_token(request)
    if token:
        payload = verify_jwt_token(token)
        return payload["sub"]
    
    # Legacy header (for migration period)
    user_id = request.headers.get("X-User-Id")
    if user_id:
        return user_id
    
    raise HTTPException(401, "Authentication required")
```

---

## 9. Implementation Checklist

### 9.1 Backend

- [ ] Create User model with role enum
- [ ] Implement password hashing (bcrypt)
- [ ] Implement JWT utilities (generate, verify)
- [ ] Create AuthService (register, login, verify)
- [ ] Create UserService (CRUD operations)
- [ ] Implement JWT authentication middleware
- [ ] Create auth router (/auth/*)
- [ ] Create user router (/users/*)
- [ ] Update existing endpoints with auth checks
- [ ] Add ownership validation to data access
- [ ] Write unit tests

### 9.2 Frontend

- [ ] Create auth store (Pinia)
- [ ] Create login page
- [ ] Create register page
- [ ] Create profile page
- [ ] Implement protected routes
- [ ] Add auth token to API client
- [ ] Handle token expiration

### 9.3 DevOps

- [ ] Add JWT_SECRET_KEY to environment variables
- [ ] Update Docker configuration
- [ ] Create database migration script

---

## 10. Testing Strategy

### 10.1 Unit Tests

- Password hashing/verification
- JWT token generation/validation
- Permission checking logic

### 10.2 Integration Tests

- Registration flow (including first-user-admin)
- Login flow
- Token validation
- Permission enforcement
- User CRUD operations

---

## 11. Future Extensions (Optional)

These features can be added later if needed:

| Feature | When to Add | Complexity |
|---------|-------------|------------|
| Password reset via email | When email server is configured | Medium |
| API keys for programmatic access | When API consumers need it | Low |
| Session management UI | When users need to manage sessions | Medium |
| Audit logging | When compliance requires it | Low |
| OAuth/Social login | When external auth is needed | High |
| Two-factor authentication | When higher security is needed | High |

---

## 12. Summary

| Aspect | Decision |
|--------|----------|
| Tables | Single `users` table |
| Roles | Enum: `admin` / `user` |
| Auth | JWT-only, 24-hour expiration |
| First user | Automatically becomes admin |
| Session tracking | None (JWT handles expiration) |
| API keys | Not included (use JWT) |
| Audit logs | Not included (optional later) |

**Estimated implementation time**: 3-4 weeks

---

## 13. References

- [JWT.io](https://jwt.io/) - JSON Web Token specification
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)
- [bcrypt Python Library](https://pypi.org/project/bcrypt/)
