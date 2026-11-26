Tom Gao

# Animal Shelter Website

This project is deployed on Vercel. The site uses Flask library for its API and page delivery, Supabase for application data and animal photos.

## Deploy on Vercel

1. Push this project to the Github repository connected to the Vercel account.
2. In Vercel, Click Create new project and import code from repository.
3. After project created, go to storage and click create storage, choose supabase as database, all env API should be auto filled.
4. In supabase, click storage and create a new bucket, name it `animal-photos`. This is where the animal photos stored at.
5. For future update, simply add commit and push it to the Github repository, vercel will auto update it in few seconds.


## Use website

New user can create account under log in page, and registed user can log in with their email and password.
Admin roll and staff role can only be set in supabase under user table and `role` value, all new user will be user role.

1. user:
user can update profile, filter and search animals, save animals, sent messages and applicaitons.

2. admin and staff:
admin and staff and do everything user can do, plus edit animals info, add or remove animals, review applications and reply messages.


## Main files
- `app.py` creates the Flask application, provide website files, and control the API modules.
- `auth.py` handles registration, login, and profile updates.
- `animals.py` handles animal listings, filters, and info.
- `applications.py` handles adoption and volunteer applications and messages.
- `admin.py` handles animal management.
- `database.py` connects to supabase and creates the tables.
- `helpers.py` contains shared authentication, validation, and photo upload helpers.
- `index.html` the front end, and `style.CSS` controls its appearance.
- `auth.js` runs in the visitor's browser. It handles form submissions, login state, animal filters, application displays, and sends requests to the Flask API under `/api/`.
- `requirements.txt` lists the Python packages Vercel installs, including Flask and Psycopg dependencies.

