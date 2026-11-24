# 🍔 CollegeBites – Smart College Cafeteria Management System

<p align="center">
  <strong>A Smarter, Faster & More Efficient Digital Cafeteria Experience</strong>
</p>

CollegeBites is a web-based smart college cafeteria management and food-ordering platform designed to digitize and simplify traditional cafeteria operations.

The platform connects students, cafeteria staff, kitchen teams, and administrators through a centralized digital system. It aims to make food ordering, payment processing, kitchen coordination, and order pickup more organized and efficient.

CollegeBites is designed around **two cafeteria counters**, with centralized order and kitchen management.

---

## 🎯 Project Objectives

- Digitize the college cafeteria ordering process.
- Reduce manual ordering and unnecessary waiting.
- Improve coordination between cafeteria counters and kitchen staff.
- Simplify online payments and order tracking.
- Provide centralized cafeteria management.
- Improve operational visibility through dashboards and reports.
- Build a scalable digital cafeteria solution.

## ✨ Key Features

### 🛒 Digital Food Ordering
- Digital cafeteria menu.
- Food item details, prices, and availability.
- Online order placement.
- Cart and order management.
- Order status tracking.

### 💳 Payment Management
- Razorpay payment gateway integration.
- Server-side payment verification.
- Payment status management.
- Digital payment records.
- Receipt generation.

### 🍽️ Cafeteria & Kitchen Management
- Two cafeteria counter operations.
- Centralized order management.
- Kitchen order coordination.
- Order preparation status management.
- Token-based order pickup workflow.

### 📱 QR-Based Order Pickup
- QR-based order identification.
- QR scanning workflow for staff.
- Order validation before handover.
- Protection against duplicate order collection.

### 📊 Administration & Analytics
- Centralized administration dashboard.
- Order and operational monitoring.
- Menu and item availability management.
- Inventory and cafeteria management modules.
- Operational reporting and analytics.

### 🔐 Security & Reliability
- Authentication and authorization.
- Role-based access control.
- Protected backend APIs.
- Input validation and error handling.
- Secure payment verification.
- Environment-based configuration.

---

## 🏗️ System Architecture

CollegeBites follows a modular application architecture.

| Component | Responsibility |
|---|---|
| Frontend | Student, staff, and admin interfaces |
| Backend | Business logic, APIs, authentication, and order processing |
| Database | Persistent application and operational records |
| Payment Gateway | Razorpay payment processing |
| Kitchen System | Food preparation and order coordination |
| Counter System | Counter operations and order handover |
| Administration | Centralized management and monitoring |
| Mobile Application | Mobile application interface and workflows |

## 🛠️ Technology Stack

### Frontend
- React.js
- TypeScript
- Vite
- Tailwind CSS
- TanStack Query
- Zustand
- Recharts
- Framer Motion
- Axios

### Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic

### Database & Infrastructure
- PostgreSQL
- Redis
- Celery
- WebSockets

### Mobile Application
- React Native
- Expo
- TypeScript
- Expo Router
- Expo SecureStore
- Expo Camera

### Integrations & Tools
- Razorpay
- Git
- GitHub
- Vercel
- Pytest
- Vitest
- Playwright

*The technology list reflects dependencies and configuration found in the supplied project repository. Actual deployed services and working integrations depend on environment configuration.*

---

## 🔄 Core Application Workflow

1. Student opens CollegeBites.
2. Student browses the cafeteria menu.
3. Student selects food items and places an order.
4. Backend validates the order and pricing.
5. Student completes payment through Razorpay or an available counter payment workflow.
6. Backend verifies the payment.
7. Order confirmation and pickup token are generated.
8. Kitchen staff receive and process the order.
9. Order status is updated.
10. Student receives the order pickup information.
11. Staff validate the QR code or token.
12. Order handover is recorded.

---

## 👨‍💻 Project Team & Contributions

### 1. Purna Sai Avvaru
**Team Lead | Complete Application Developer**

- Led the CollegeBites project from concept to implementation.
- Developed the complete application.
- Designed and implemented the frontend.
- Developed backend APIs and application logic.
- Worked on database integration and management.
- Integrated Razorpay payment functionality.
- Developed cafeteria ordering and management workflows.
- Implemented order management and QR-based pickup workflows.
- Worked on application security and reliability.
- Coordinated overall project development and integration.

### 2. Srikar
**Deployment & Testing**

- Contributed to application deployment activities.
- Assisted with deployment configuration.
- Performed application testing.
- Helped identify bugs and functional issues.
- Supported testing of application workflows.

### 3. Harishini
**Architecture Design | System Design & Testing**

- Contributed to application architecture design.
- Worked on system design and structural planning.
- Assisted in reviewing application workflows.
- Participated in application testing.
- Helped identify system-level improvements.

---

## 🚀 Project Vision

Our vision is to transform traditional college cafeterias into digitally managed food-service environments.

CollegeBites aims to create a centralized cafeteria ecosystem that makes food ordering easier for students and daily cafeteria operations more organized for staff and administrators.

The long-term goal is to develop a scalable solution that can support the evolving requirements of modern educational institutions.

## 📌 Project Status

**Status: Active Development**

CollegeBites is undergoing continuous development, testing, and improvement. Features and workflows are refined based on application requirements and testing results.

## 🤝 Contributions

We welcome suggestions, feedback, bug reports, and improvements.

To contribute:

1. Fork this repository.
2. Create a new feature branch.
3. Implement your changes.
4. Test your changes.
5. Submit a pull request with a clear description.

## 📄 License

A license should be added to the repository before external redistribution or reuse.

---

<p align="center">
  <strong>Built with dedication by Team CollegeBites ❤️</strong>
  <br/>
  <strong>Team Lead & Developer: Purna Sai Avvaru</strong>
</p>
