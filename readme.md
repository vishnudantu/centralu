# Central Uniform Sizer (Centalu)

**Production URL:** https://sizer.centralclothing.in  
**Stack:** FastAPI + SQLite + React (MUI CDN) + Docker + Nginx + Let's Encrypt

---

## 1. What This App Does

A single-page web application for schools to upload student body measurement Excel files and automatically calculate uniform garment sizes (Shirts, Pants, Skirts, Shorts, Sports T-Shirts, School T-Shirts, Sports Track Pants) against configurable global master size charts.

**Core Workflow:**
1. Upload Excel → 2. Auto-detect column mapping → 3. Process sizing engine → 4. Download vendor-ready Excel

---

## 2. Architecture

### Local Development (Windows)
Browser → Nginx (localhost:3000) → Static HTML/JS ↓ FastAPI (localhost:8000) → SQLite (data/app.db)


### Production (Contabo VPS)
Internet → Nginx (Host, 443 SSL) → Docker Containers (localhost only) │ ┌───────────────────┴───────────────────┐ ↓ ↓ Frontend (127.0.0.1:3000) Backend (127.0.0.1:8000) (Nginx serves MUI React) (FastAPI + SQLite)


**Security:** Backend and frontend communicate via `/api` reverse proxy. Neither container exposes public ports directly.

---

## 3. Project Structure

centalu/ ├── docker-compose.yml # Production orchestration ├── README.md # This file ├── backend/ │ ├── Dockerfile │ ├── requirements.txt │ ├── main.py # FastAPI endpoints │ ├── db/ │ │ ├── init.py │ │ └── database.py # SQLite operations │ └── core/ │ ├── init.py │ ├── size_engine.py # Measurement normalization + size matching │ └── exporter.py # Excel generation (3 sheets: Data, Errors, Summary) └── frontend/ ├── Dockerfile # Nginx alpine ├── nginx.conf # Reverse proxy /api to backend └── index.html # Single-file React + MUI app (zero build)


---

## 4. Database Schema (SQLite)

| Table | Purpose |
|-------|---------|
| `users` | Authentication (default: admin/admin123) |
| `schools` | School registry with academic year |
| `global_size_charts` | Master size charts per garment type |
| `allowances` | Measurement added to body to get garment size |
| `history` | Audit log of every processing batch |

---

## 5. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/login` | POST | Authenticate, returns token |
| `/schools` | GET/POST/PUT/DELETE | CRUD schools |
| `/charts` | GET | Fetch all garment charts |
| `/charts/{item}` | POST | Save chart for garment |
| `/allowances` | GET | List all allowances |
| `/allowances/{item}` | POST | Update allowance value |
| `/template` | GET | Download blank Excel template |
| `/process` | POST | Upload Excel + mapping JSON, process sizing |
| `/download` | GET | Download last processed Excel |
| `/history` | GET | List processing history |

---

## 6. Excel Template Format

The master template contains these exact headers (auto-detected by frontend):

| Column | Used For |
|--------|----------|
| Enrollment Code | Student ID |
| Student Name | Name |
| Gender | Determines skirt vs pant/shorts |
| Admission Type | Reference |
| House Colour | Reference |
| Class Number | Grade level (1-10 etc.) |
| Class Name | Section name |
| Chest | Body chest measurement (for shirts/tees) |
| Waist | Body waist measurement (for bottoms/track pants) |
| Length | Optional reference |

---

## 7. Auto-Mapping Logic

The frontend automatically maps Excel headers to internal fields by normalizing strings:

| Detected Header | Maps To |
|-----------------|---------|
| `Enrollment Code`, `enroll`, `roll no` | `enr` |
| `Student Name`, `name` (not class name) | `name` |
| `Class Number`, `class no`, `grade` | `class_num` |
| `Class Name`, `section` | `class_name` |
| `Gender`, `sex` | `gender` |
| `Admission Type`, `type` | `adm_type` |
| `House Colour`, `house color` | `house` |
| `Chest`, `Body Chest` | `chest` |
| `Waist`, `Body Waist` | `waist` |
| `Length` | `length` (optional) |

---

## 8. Sizing Engine Logic

1. **Normalize:** Extract numeric value from measurement string (handles `32"`, `76 cm`, etc.)
2. **Calculate Garment:** Body measurement + allowance = garment measurement
3. **Match Size:** Find the smallest chart size where `chart_value >= garment_value`
4. **Determine Bottom Type:**
   - Girls (`GIRL`/`F`/`FEMALE`) → Skirt
   - Boys Grades 1-5 (`BOY`/`M`/`MALE`, class starts with 1-5) → Shorts
   - Boys Grades 6+ → Pant
   - Unrecognized → Shorts (fallback)

---

## 9. Deployment Guide

### Prerequisites
- Ubuntu 24.04 VPS
- Docker + Docker Compose plugin
- Domain with A record pointing to VPS IP
- Nginx + Certbot installed on host

### Steps
1. Clone repo to `/opt/centralu`
2. Build and run: `docker compose up -d --build`
3. Configure Nginx reverse proxy for domain
4. Run `certbot --nginx -d yourdomain.com`
5. Containers bind to `127.0.0.1` only; Nginx handles public access

### Multi-App Isolation (Same VPS)
To run multiple apps on one VPS without interference:

| App | Local Port | Domain |
|-----|-----------|--------|
| centralu | 127.0.0.1:3000/8000 | sizer.centralclothing.in |
| app2 | 127.0.0.1:4000/9000 | app2.centralclothing.in |

Each app lives in `/opt/appname/` with its own Docker network. Nginx routes by `server_name`. They cannot see each other.

---

## 10. Known Limitations

- **SQLite:** Single-user friendly. For 10+ concurrent users or multi-server setup, migrate to PostgreSQL/MariaDB.
- **File Upload:** Single-threaded processing. Large files (1000+ students) may take 10-30 seconds.
- **No RBAC:** Only single `admin` user. No roles or permissions.
- **History:** Basic audit log. No PDF generation or advanced analytics yet.
- **Frontend:** Single `index.html` with Babel in-browser transpilation. For massive scale, switch to Vite build pipeline.

---

## 11. Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `PYTHONUNBUFFERED` | `1` | Python stdout logging |

---

## 12. Troubleshooting

| Issue | Fix |
|-------|-----|
| `404` on `/api/...` | Ensure Nginx `location /api/` block exists and backend container is running |
| `502 Bad Gateway` | Backend crashed. Check `docker logs centalu-backend` |
| SSL expired | `certbot renew --nginx` or wait for auto-renewal cron |
| Blank page | Backend not serving? Check `docker ps` and `curl http://127.0.0.1:8000/` |
| Chart Missing errors | Add size rows in Configuration → Master Charts for ALL garment types before processing |

---

## 13. Future Roadmap

- [ ] Migrate to PostgreSQL/MariaDB for multi-user concurrency
- [ ] Add user roles (admin vs operator)
- [ ] PDF export alongside Excel
- [ ] Bulk school import via CSV
- [ ] Analytics dashboard (charts of size distributions)
- [ ] Mobile-responsive refinements
- [ ] Switch frontend to Vite + proper build pipeline
- [ ] API token authentication (JWT) instead of static token

---

**Maintainer:** Vishnu Dantu  
**Repository:** https://github.com/vishnudantu/centralu