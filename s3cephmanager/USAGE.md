# CephS3Manager — Ghid de utilizare a interfeței

> Documentație detaliată a tuturor paginilor și funcționalităților UI.
> Pentru instrucțiuni de instalare și deployment, consultați [`README.md`](README.md).

---

## Cuprins

1. [Bara laterală (Sidebar)](#1-bara-laterală-sidebar)
2. [Pagina Connections (Conexiuni)](#2-pagina-connections-conexiuni)
3. [Pagina Buckets](#3-pagina-buckets)
4. [Pagina Objects (Obiecte / Fișiere)](#4-pagina-objects-obiecte--fișiere)
5. [Pagina Users (Utilizatori RGW)](#5-pagina-users-utilizatori-rgw)
6. [Pagina Settings (Setări)](#6-pagina-settings-setări)
7. [Fluxuri de lucru comune](#7-fluxuri-de-lucru-comune)
8. [Note importante](#8-note-importante)

---

## 1. Bara laterală (Sidebar)

Bara laterală este vizibilă pe toate paginile și conține:

| Element | Descriere |
|---|---|
| **Logo / Titlu** | Afișează „CephS3Manager"; click → pagina Connections |
| **Connections** | Navighează la `/` — gestionare conexiuni S3/RGW |
| **Buckets** | Navighează la `/buckets` — vizualizare și gestionare bucket-uri |
| **Objects** | Navighează la `/objects` — browsing și gestionare fișiere |
| **Users** | Navighează la `/users` — gestionare utilizatori RGW Admin API |
| **Settings** | Navighează la `/settings` — preferințe aplicație |
| **Dark / Light toggle** | Comutator temă întunecată ↔ luminoasă (stare persistată per sesiune) |
| **Conexiune activă** | Bannerul verde din josul sidebar-ului afișează numele conexiunii active |

> **Redirecționare automată**: dacă nu există nicio conexiune activă, paginile Buckets, Objects și Users redirecționează automat la pagina Connections.

---

## 2. Pagina Connections (Conexiuni)

**URL**: `/`

Aceasta este pagina de start. Toate conexiunile salvate (stocate în SQLite local) sunt afișate sub formă de carduri.

### 2.1 Câmpurile unei conexiuni

| Câmp | Obligatoriu | Descriere |
|---|---|---|
| **Name** | ✅ | Nume descriptiv al conexiunii (ex: `prod-ceph`, `dev-cluster`) |
| **Endpoint** | ✅ | URL-ul S3 intern (ex: `http://rook-ceph-rgw-my-store.rook-ceph:80`) |
| **Access Key** | ✅ | Cheia de acces S3 a utilizatorului admin |
| **Secret Key** | ✅ | Cheia secretă corespunzătoare |
| **Region** | ❌ | Region S3 (default: `us-east-1`; lăsați ca atare pentru Ceph) |
| **Verify SSL** | ❌ | Validare certificat SSL (dezactivați pentru self-signed) |
| **Public Endpoint** | ❌ | Endpoint public/extern pentru generarea presigned URL-urilor (ex: `https://s3.company.com`) |
| **Admin Endpoint** | ❌ | URL Admin Ops API (ex: `http://rook-ceph-rgw-my-store.rook-ceph:80/admin`) — necesar pentru pagina Users |

### 2.2 Acțiuni

- **New Connection** (buton în header): deschide formularul de creare conexiune nouă
- **Test** (buton pe card): verifică conectivitatea — listează bucket-urile și afișează mesaj de succes sau eroare
- **Activate** (buton pe card): setează conexiunea ca activă; badge-ul din sidebar se actualizează
- **Edit** (buton pe card): modifică câmpurile conexiunii existente
- **Delete** (buton pe card): șterge conexiunea definitiv (necesită confirmare)

### 2.3 Badge-uri de stare

| Badge | Semnificație |
|---|---|
| 🟢 **ACTIVE** | Conexiunea curentă activă |
| 🔵 **Admin API** | Conexiunea are Admin Endpoint configurat |

---

## 3. Pagina Buckets

**URL**: `/buckets`

Afișează toți bucket-urile din conexiunea activă sub formă de tabel.

### 3.1 Header-ul paginii

- **Refresh** (🔄): reîncarcă lista bucket-urilor și statisticile globale
- **New Bucket**: deschide dialogul de creare bucket nou

### 3.2 Tabelul de bucket-uri

Coloane:

| Coloană | Descriere |
|---|---|
| **Name** | Numele bucket-ului |
| **Objects** | Numărul de obiecte (dacă Admin API este disponibil) |
| **Size** | Dimensiunea totală (dacă Admin API este disponibil) |
| **Created** | Data și ora creării |
| **Actions** | Butoane de acțiune per rând |

Acțiuni per rând:

| Acțiune | Descriere |
|---|---|
| 📂 **Browse** | Navighează la pagina Objects și deschide acest bucket |
| ⚙️ **Settings** | Deschide dialogul de setări avansate ale bucket-ului (5 tab-uri) |
| 🗑️ **Delete** | Șterge bucket-ul (opțional: cu purjare obiecte) |

### 3.3 Dialogul New Bucket

Câmpuri:

- **Bucket name**: numele noului bucket (obligatoriu; respectă regulile DNS S3)
- **Region**: regiunea de creare (default: `us-east-1`)
- **User permissions** (vizibil doar când Admin API este configurat): permite configurarea accesului per utilizator RGW direct la creare

Secțiunea **User Permissions**:
- Dropdown cu lista tuturor utilizatorilor RGW
- Selector nivel acces: `read` / `write` / `read_write` / `full`
- **Add** — adaugă utilizatorul în lista de permisiuni
- Lista permisiunilor configurate cu buton **Remove** per intrare

> Permisiunile sunt salvate ca S3 Bucket Policy imediat după crearea bucket-ului.

### 3.4 Dialogul Bucket Settings (⚙️)

Dialog cu 5 tab-uri pentru configurarea avansată a unui bucket existent.

#### Tab: Policy

Editor JSON pentru S3 Bucket Policy:
- Câmp textarea cu policy-ul JSON curent
- **Save Policy**: aplică policy-ul modificat
- **Delete Policy**: șterge policy-ul complet

> ⚠️ Editarea manuală a policy-ului poate suprascrie permisiunile gestionate din tab-ul Permissions.

#### Tab: CORS

Gestionarea regulilor CORS (Cross-Origin Resource Sharing):

- **Add Rule** — adaugă o regulă nouă cu câmpurile:
  - **Allowed Origins**: origini permise (ex: `https://app.company.com`, `*`)
  - **Allowed Methods**: metode HTTP (GET, PUT, POST, DELETE, HEAD)
  - **Allowed Headers**: headere permise (ex: `*`)
  - **Expose Headers**: headere expuse în răspuns
  - **Max Age Seconds**: durata de cache a preflight-ului

- Regulile existente sunt afișate în tabel cu buton **Delete** per regulă
- **Save CORS**: salvează toate regulile
- **Delete All**: șterge configurația CORS complet

#### Tab: Versioning

Control versioning S3:

- **Status curent**: afișat ca `Enabled`, `Suspended` sau `Not configured`
- **Enable Versioning**: activează versioning-ul (fișierele șterse/suprascrise sunt păstrate)
- **Suspend Versioning**: suspendă crearea de versiuni noi (versiunile existente sunt păstrate)

> ⚠️ Versioning-ul activat nu poate fi dezactivat complet, doar suspendat.

#### Tab: Lifecycle

Gestionarea regulilor de lifecycle (expirare și tranziție automată fișiere):

**Tabelul regulilor existente** — coloane:

| Coloană | Descriere |
|---|---|
| ID | Identificatorul regulii |
| Prefix | Filtru prefix (gol = toate obiectele) |
| Expire | Expiră obiecte după N zile |
| NoncurVer | Șterge versiunile non-curente după N zile |
| AbortMP | Anulează upload-urile multipart incomplete după N zile |
| Transition | Mută obiectele în clasa de stocare specificată după N zile |
| Status | Enabled / Disabled |
| Del | Buton ștergere regulă |

**Formularul pentru regulă nouă / actualizare**:

| Câmp | Descriere |
|---|---|
| **Rule ID** | ID opțional; dacă gol, se generează automat (`rule-xxxxxxxx`) |
| **Prefix filter** | Aplică regula doar obiectelor cu acest prefix (gol = tot bucket-ul) |
| **Expire objects after (days)** | Șterge automat obiectele curente după N zile (0 = dezactivat) |
| **Delete old versions after (days)** | Șterge versiunile non-curente după N zile (necesită versioning activ; 0 = dezactivat) |
| **Abort incomplete multipart after (days)** | Curăță upload-urile multipart abandonate după N zile (0 = dezactivat) |
| **Transition after (days)** | Mută obiectele în altă clasă de stocare după N zile (0 = dezactivat) |
| **Storage class** | Clasa țintă pentru tranziție: `GLACIER`, `STANDARD_IA`, `COLD`, etc. |
| **Rule enabled** | Checkbox — activează/dezactivează regula |

Butoane:
- **Add / Update Rule**: salvează regula (actualizează dacă există deja un Rule ID identic)
- **Delete All Rules**: șterge toate regulile de lifecycle de pe bucket

> **Exemplu arhivare**: Prefix gol, Transition after = `30` → `GLACIER`, Expire objects after = `365` → obiectele sunt mutate în GLACIER după 30 zile și șterse după 1 an.

#### Tab: Permissions

Gestionarea vizuală a accesului utilizatorilor RGW la bucket (via S3 Bucket Policy):

- **Tabelul permisiunilor** — afișează utilizatorii cu acces și nivelul lor:

| Nivel | Acțiuni permise |
|---|---|
| `read` | GetObject, ListBucket, GetObjectVersion, GetBucketLocation |
| `write` | PutObject, DeleteObject, AbortMultipartUpload, PutObjectAcl |
| `read_write` | Combinație read + write |
| `full` | `s3:*` (acces complet) |

- Dropdown cu lista utilizatorilor RGW disponibili
- Selector nivel acces
- **Add**: adaugă/actualizează permisiunea și o salvează imediat în Bucket Policy
- **Remove** (per utilizator): revocă accesul și actualizează policy-ul imediat

> Permisiunile gestionate prin acest tab au Sid-ul cu prefix `_CephS3Mgr-`. Celelalte statement-uri din policy rămân neatinse.

---

## 4. Pagina Objects (Obiecte / Fișiere)

**URL**: `/objects`

Browser de fișiere S3 cu navigare hierarhică (folder-uri virtuale bazate pe prefix `/`).
Lista de obiecte este redată cu **AG Grid** — oferă paginare client-side, filtrare live și selecție bulk.

### 4.1 Panoul stâng — Arbore de folder-uri

- Afișează bucket-ul activ și structura de folder-uri (prefix-uri)
- Click pe un folder → navighează la acel prefix; arborele se actualizează și afișează sub-folder-urile
- Click pe **bucket name** → revine la rădăcina bucket-ului
- Sincronizat cu breadcrumb-ul și grila principală

### 4.2 Breadcrumb

- Afișează calea curentă: `bucket-name / folder / subfolder /`
- Click pe orice segment → navighează direct la acel nivel
- Util pentru navigare rapidă înapoi în ierarhie

### 4.3 Quick filter

- Câmpul **Quick filter...** din colțul dreapta-sus filtrează rândurile din grilă **instant**, pe client, fără apel la server
- Filtrare după coloana **Name**; folderele și fișierele care nu se potrivesc dispar din listă
- Ștergerea filtrului (× sau Backspace) restaurează lista completă

### 4.4 Toolbar (bara de instrumente)

| Buton | Scurtătură | Descriere |
|---|---|---|
| **Upload ▾** | `U` | Deschide dialogul de upload fișiere; ▾ deschide meniu cu „Upload folder" |
| **Download** | — | Descarcă obiectele selectate (fișiere individuale sau arhivă) |
| **Copy** | — | Copiază obiectele selectate în același bucket (cu prefix destinație nou) |
| **Delete Selected** | — | Șterge obiectele selectate (cu dialog de confirmare) |
| **New Folder** | `N` | Creează un folder virtual nou (obiect placeholder cu sufix `/`) |
| **Copy to Bucket** | — | Copiază obiectele selectate cross-bucket (server-side, fără descărcare locală) |
| **Refresh** | `R` | Reîncarcă lista obiectelor din prefix-ul curent |

### 4.5 Grila de obiecte (AG Grid)

Grila afișează conținutul prefix-ului curent cu paginare client-side.

**Coloane:**

| Coloană | Descriere |
|---|---|
| ☑️ | Checkbox selecție (header-checkbox = selectează tot) |
| 📁 / 📄 | Iconiță tip: folder (galben), fișier (gri), `..` parinte (albastru) |
| **Name** | Numele fișierului sau folder-ului; click pe folder / `..` → navighează |
| **Size** | Dimensiunea fișierului formatată (ex: `12.4 MB`); `—` pentru foldere |
| **Modified** | Data și ora ultimei modificări |
| 👁 | (fișier) Previzualizare inline în dialog |
| ⬇ | (fișier) Descărcare directă prin presigned URL |
| 📋 | (fișier / folder) Copiere în același bucket |
| ✏ | (fișier) Redenumire / mutare (copiere + ștergere) |
| 🔗 | (fișier) Generare presigned URL temporar |
| 🗑 | (fișier / folder) Ștergere (folder = recursiv cu confirmare) |

**Paginare footer:**

- Selector **Page Size**: 25 / 50 / 100 / 250 rânduri per pagină
- Navigare pagini: `|<` `<` `>` `>|`
- Contor: `1 to N of Total`

> **Notă**: Prima linie a grilei poate fi `..` (parinte) dacă vă aflați într-un sub-folder. Click pe ea revine la nivelul superior.

### 4.6 Selecție și acțiuni bulk

1. Bifați rândurile dorite cu checkbox-urile din coloana ☑️
2. Contorul **N selected** apare în bara de sub toolbar
3. Click **Delete selected** → dialog de confirmare → ștergere în loturi de 1 000 chei (limita S3)
4. Alternativ, folosiți **Copy to Bucket** sau **Download** din toolbar pentru obiectele selectate

### 4.7 Dialogul Upload

- Suportă selecție multiplă de fișiere sau **drag & drop**
- Progres per fișier: bara procentuală, viteză (MB/s), ETA
- Upload multipart automat pentru fișiere mari (prag configurabil în Settings, implicit 64 MB)
- Câmpul **Prefix** permite specificarea unui subfolder destinație manual

### 4.8 Dialogul Presigned URL

- Afișează URL-ul generat cu data și ora expirării
- **Expiry**: configurat în Settings (implicit: 3600 s / 1 oră)
- `ResponseContentDisposition: attachment` → browserul descarcă automat fișierul
- **Copy** — copiază URL-ul în clipboard
- **Open** — deschide URL-ul în tab nou (declanșează descărcarea)

### 4.9 Dialogul Copy to Bucket (cross-bucket)

1. Selectați obiectele dorite
2. Click **Copy to Bucket** în toolbar
3. Alegeți bucket-ul destinație din dropdown
4. (Opțional) specificați un prefix destinație
5. Click **Copy** — copiere server-side, fără descărcare locală

### 4.10 Scurtături tastatură

| Tastă | Acțiune |
|---|---|
| `U` | Deschide dialogul Upload |
| `N` | Deschide dialogul New Folder |
| `R` | Reîncarcă lista obiectelor |
| `Escape` | Închide dialogul deschis |

---

## 5. Pagina Users (Utilizatori RGW)

**URL**: `/users`

> ⚠️ **Necesită Admin Endpoint configurat** în conexiunea activă. Dacă Admin API nu este disponibil, pagina afișează un mesaj informativ.

### 5.1 Lista utilizatorilor

- Tabel cu toți utilizatorii RGW din clusterul Ceph
- Coloane: **UID**, **Display Name**, **Email**, **Suspended**, **Actions**
- **Refresh**: reîncarcă lista

### 5.2 Butonul New User

Deschide formularul de creare utilizator nou cu câmpurile:

| Câmp | Obligatoriu | Descriere |
|---|---|---|
| **User ID (UID)** | ✅ | Identificator unic al utilizatorului |
| **Display Name** | ✅ | Numele afișat |
| **Email** | ❌ | Adresa de email |
| **Max Buckets** | ❌ | Numărul maxim de bucket-uri permise (default: 1000) |
| **Generate Key** | ❌ | Generează automat o pereche de chei S3 (implicit activat) |

### 5.3 Dialogul User Details (4 tab-uri)

Click pe un utilizator din tabel → se deschide dialogul cu 4 tab-uri.

#### Tab: Info

Informații generale și editare:

| Câmp | Descriere |
|---|---|
| **UID** | Identificatorul utilizatorului (read-only) |
| **Display Name** | Modificabil — click Save pentru salvare |
| **Email** | Modificabil |
| **Max Buckets** | Numărul maxim de bucket-uri |
| **Suspended** | Toggle — suspendă/reactivează contul utilizatorului |

Statistici de utilizare (dacă disponibile):
- **Storage used**: spațiu total ocupat
- **Objects**: număr total de obiecte
- **Buckets**: număr de bucket-uri deținute

Butoane:
- **Save Changes**: aplică modificările câmpurilor editabile
- **Suspend / Unsuspend**: suspendă sau reactivează contul
- **Delete User**: șterge utilizatorul definitiv (cu opțiunea de a purja datele)

#### Tab: Keys

Gestionarea cheilor S3 ale utilizatorului:

- Tabel cu toate perechile de chei: **Access Key** și **Secret Key** (ascuns implicit, click 👁️ pentru vizualizare)
- **Generate New Key**: generează o nouă pereche de chei și o adaugă
- **Delete** (per cheie): șterge cheia selectată

> ⚠️ Cheia secretă este vizibilă o singură dată la generare. Salvați-o în siguranță.

#### Tab: Quota

Configurarea limitelor de stocare per utilizator:

| Câmp | Descriere |
|---|---|
| **Quota enabled** | Activează/dezactivează limitele |
| **Max size (GB)** | Limita de spațiu în GB (-1 = nelimitat) |
| **Max objects** | Numărul maxim de obiecte (-1 = nelimitat) |

- **Save Quota**: aplică configurația

> Ceph stochează quota intern în KB; interfața convertește automat GB ↔ KB.

#### Tab: Buckets

Lista bucket-urilor deținute de utilizator:

- Tabel cu: **Bucket Name**, **Size**, **Objects**, **Created**
- **Browse** (per bucket): navighează la Objects în acel bucket
- **Link Bucket**: reasociază un bucket existent la acest utilizator (necesită Bucket ID)

---

## 6. Pagina Settings (Setări)

**URL**: `/settings`

Preferințele sunt stocate per sesiune (`app.storage.user`) și aplicate imediat.

| Setare | Descriere | Default |
|---|---|---|
| **Default Region** | Regiunea implicită la crearea bucket-urilor | `us-east-1` |
| **Page Size** | Numărul de obiecte afișate per pagină în Objects | `100` |
| **Presigned URL Expiry (seconds)** | Durata de valabilitate a presigned URL-urilor | `3600` (1 oră) |
| **Upload Chunk Size (MB)** | Dimensiunea chunk-urilor pentru upload multipart | `8` MB |
| **Upload Multipart Threshold (MB)** | Pragul de la care se folosește upload multipart | `64` MB |

- **Save Settings**: salvează toate preferințele

---

## 7. Fluxuri de lucru comune

### 7.1 Configurare conexiune nouă

1. Navigați la **Connections** (pagina de start)
2. Click **New Connection**
3. Completați Endpoint, Access Key, Secret Key
4. (Opțional) Adăugați Admin Endpoint pentru funcționalități RGW avansate
5. (Opțional) Adăugați Public Endpoint dacă presigned URL-urile trebuie să fie accesibile din exterior
6. Click **Test** pentru verificare conectivitate
7. Click **Activate** pentru a o seta ca conexiune activă

### 7.2 Upload fișiere

1. Activați o conexiune
2. Navigați la **Objects**
3. (Opțional) Navigați în folder-ul dorit folosind arborele din stânga sau breadcrumb
4. Click **Upload** sau apăsați `U`
5. Selectați fișierele sau trageți-le în zona de drop
6. Urmăriți progresul în dialogul de upload

### 7.3 Generare link de descărcare temporar (Presigned URL)

1. Navigați la **Objects** și localizați fișierul dorit
2. Click 🔗 **Presigned URL** pe rândul fișierului
3. URL-ul generat este afișat cu data expirării
4. Click **Copy** pentru a copia în clipboard sau **Open** pentru a descărca direct
5. Link-ul expiră după perioada configurată în Settings (default: 1 oră)

> Browserul va descărca automat fișierul când accesează URL-ul (nu îl afișează inline).

### 7.4 Configurare lifecycle pentru arhivare automată

1. Navigați la **Buckets**
2. Click ⚙️ **Settings** pe bucket-ul dorit
3. Deschideți tab-ul **Lifecycle**
4. Completați formularul:
   - **Transition after**: `30` zile, **Storage class**: `GLACIER`
   - **Expire objects after**: `365` zile
5. Click **Add / Update Rule**
6. Regula este salvată imediat pe bucket

### 7.5 Creare utilizator RGW cu acces la bucket

1. Navigați la **Users** → **New User**
2. Completați UID, Display Name → **Create**
3. Din tab-ul **Keys**: notați Access Key și Secret Key generate
4. Navigați la **Buckets** → ⚙️ **Settings** pe bucket-ul dorit
5. Tab **Permissions**: selectați utilizatorul nou, nivel `read_write`, click **Add**
6. Permisiunea este salvată imediat în Bucket Policy

### 7.6 Copiere fișiere între bucket-uri

1. Navigați la **Objects** în bucket-ul sursă
2. Bifați fișierele dorite (checkbox-uri)
3. Click **Copy to Bucket** în toolbar
4. Selectați bucket-ul destinație
5. (Opțional) specificați un prefix destinație
6. Click **Copy** — fișierele sunt copiate server-side (fără descărcare locală)

---

## 8. Note importante

### Securitate
- **Cheile S3** sunt stocate în baza de date SQLite locală (criptare recomandată la nivel de OS sau volum k8s)
- **Admin API** permite operații distructive (ștergere utilizatori, purjare date) — restricționați accesul la interfață
- **Presigned URL-urile** sunt publice pe durata valabilității; nu le distribuiți pentru fișiere sensibile
- Permisiunile din tab-ul Permissions folosesc S3 Bucket Policy standard — auditați regulat

### Limitări cunoscute
- Versioning-ul odată activat nu poate fi complet dezactivat (S3 standard)
- Tab-ul Lifecycle necesită ca Ceph RGW să fie configurat cu driver lifecycle activ
- Clasa de stocare `GLACIER` în Ceph RGW necesită backend de stocare configurat corespunzător
- Operațiile de ștergere pe foldere virtuale cu mii de obiecte pot dura câteva minute

### Performanță
- **Page Size** din Settings afectează viteza de încărcare a paginii Objects (valori mici = mai rapid)
- Upload-urile multipart mari (>64 MB implicit) sunt mai fiabile pe conexiuni instabile
- Statisticile din tabelul Buckets (Objects, Size) necesită Admin API și pot crește ușor timpul de încărcare

### Teme
- Tema **Dark** (implicit) și **Light** se comută din sidebar
- Preferința de temă este salvată per sesiune browser (storage local)

---

*CephS3Manager v1.1 · NiceGUI + FastAPI + AG Grid + boto3 + Ceph RGW*
