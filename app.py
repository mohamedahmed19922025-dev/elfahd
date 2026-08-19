import base64
import datetime
import io
import os
import re
import uuid
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACK22 = os.path.join(BASE_DIR, "back22.jpg")
BACK33 = os.path.join(BASE_DIR, "back33.jpg")

st.set_page_config(page_title="ZoOz", page_icon="🗂️", layout="wide")

DATE_COLS = [
    "تاريخ إستلام الورق", "تاريخ 46", "تاريخ الكشف",
    "التاريخ المتوقع الوصول", "تاريخ السداد", "تاريخ الاعتماد",
    "تاريخ الوصول الفعلي", "تاريخ السماح",
]


# =========================
# 1) الخلفية والستايل
# =========================

@st.cache_data
def get_base64_image(img_path):
    if os.path.exists(img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


def set_background(img_path):
    base64_string = get_base64_image(img_path)
    if base64_string:
        st.markdown(f"""
            <style>
            [data-testid="stAppViewContainer"] {{
                background-image: url("data:image/jpg;base64,{base64_string}");
                background-size: cover;
                background-position: center;
                background-attachment: fixed;
            }}
            .stApp {{ background: transparent; }}
            </style>
        """, unsafe_allow_html=True)


def apply_theme():
    st.markdown("""
        <style>
        header, [data-testid="stHeader"] { background-color: #14101000 !important; color: white !important; }
        header a { color: white !important; padding: 6px 14px; border-radius: 8px; transition: 0.3s; }
        header a:hover { background-color: #5fc9f3 !important; color: white !important; font-weight: bold; }
        header a[aria-current="page"] { background-color: #0092ca !important; color: white !important; font-weight: bold; }
        header * , [data-testid="stHeader"] * { color: white !important; }
        [data-testid="stExpander"] summary { background-color: #0092ca; color: white; padding: 5px 10px; border-radius: 5px; font-weight: bold; }
        [data-testid="stExpander"] details:hover summary { background-color: #5fc9f3; }
        h1, h2, h3, h4, h5, h6, p, label, span { color: white !important; }
        div.stButton > button { background-color: #0092ca; color: white; border-radius: 10px; padding: 8px 16px; border: none; font-weight: bold; transition: 0.3s; }
        div.stButton > button:hover { background-color: #5fc9f3 !important; color: white !important; border: 2px solid #0092ca; }
        section[data-testid="stSidebar"] * { color: black !important; }
        div[data-testid="stDataFrame"] { border: 3px solid #ffffff !important; border-radius: 15px !important; overflow: hidden !important; }
        .stMetric label, .stMetric div { color: white !important; }
        </style>
    """, unsafe_allow_html=True)


def show_footer():
    st.markdown(
        "<div style='position: fixed; bottom: 10px; left: 10px; color: #5fc9f3; font-size: 18px;'>ZoOz ©</div>",
        unsafe_allow_html=True,
    )


# =========================
# 2) المستخدمون والصلاحيات من secrets
# =========================

def get_users():
    try:
        raw = st.secrets.get("users", {})
    except Exception:
        raw = {}
    users = {}
    for name, info in raw.items():
        companies = info.get("companies", [])
        if isinstance(companies, str):
            companies = [companies]
        users[str(name)] = {
            "password": str(info.get("password", "")),
            "role": str(info.get("role", "viewer")),
            "access": str(info.get("access", "view")),
            "companies": [str(c) for c in companies],
        }
    return users


def is_admin(user):
    return user.get("role") in ("main", "admin")


def can_edit(user):
    return is_admin(user) or user.get("access") == "edit"


def user_allowed_companies(user):
    if is_admin(user):
        return None  # كل الشركات
    return user.get("companies") or None


def filter_by_access(df, user):
    """يحجز البيانات حسب صلاحيات المستخدم (قراءة لشركات معينة فقط)."""
    allowed = user_allowed_companies(user)
    if allowed is None or df.empty:
        return df
    if "إسم الشركة" not in df.columns:
        return df
    return df[df["إسم الشركة"].astype(str).str.strip().isin(allowed)].reset_index(drop=True)


# =========================
# 3) Google Sheets
# =========================

def get_sheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = dict(st.secrets.get("gcp_service_account", {}))
    if not info:
        raise ValueError("gcp_service_account غير موجود في secrets")
    creds = Credentials.from_service_account_info(info, scopes=scope)
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["google_sheet_id"])


def get_worksheet():
    return get_sheet().get_worksheet(0)


def _cell_fmt(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp) or isinstance(v, datetime.datetime) or isinstance(v, datetime.date):
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            return str(v)
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    return str(v)


def load_data():
    ws = get_worksheet()
    headers = ws.row_values(1)
    if not headers:
        return pd.DataFrame()
    rows = ws.get_all_values()[1:]
    df = pd.DataFrame(rows, columns=headers)
    # تحويل الخلايا الفارغة لقيم NaN
    df = df.replace("", pd.NA)
    # تحويل أعمدة التواريخ
    if "رقم الشهادة" in df.columns:
        df["رقم الشهادة"] = df["رقم الشهادة"].apply(
            lambda x: str(int(float(x))) if pd.notna(x) and str(x).strip() != "" else ""
        )
    if "السنة" in df.columns:
        df["السنة"] = df["السنة"].apply(
            lambda x: str(int(float(x))) if pd.notna(x) and str(x).strip() != "" else ""
        )
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "م" in df.columns:
        df = df.drop(columns=["م"])
    return df


def save_data(df):
    ws = get_worksheet()
    headers = df.columns.astype(str).tolist()
    body = [headers]
    for _, row in df.iterrows():
        body.append([_cell_fmt(row[c]) for c in df.columns])
    ws.clear()
    ws.update(body)


def to_excel_bytes(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="البيانات")
    return buf.getvalue()


# =========================
# 4) دوال مساعدة
# =========================

def clean_value(val):
    if val is None:
        return "_____"
    if isinstance(val, float) and pd.isna(val):
        return "_____"
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() == "nan":
        return "_____"
    return val_str


def safe_date(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def safe_val(val):
    return "______" if pd.isna(val) or val is None or val == "" else val


def clean_date(val):
    if pd.isna(val) or val is None or val == "":
        return "______"
    try:
        return pd.to_datetime(val).strftime("%Y-%m-%d")
    except Exception:
        return val


def get_sorted_companies(df):
    if df.empty:
        return []
    return df["إسم الشركة"].value_counts().index.tolist()


def get_sorted_authorizations(df):
    if df.empty or "التوكيل" not in df.columns:
        return ["none"]
    counts = df["التوكيل"].value_counts()
    sorted_auth = counts.index.tolist()
    return ["none"] + sorted_auth if len(sorted_auth) > 0 else ["none"]


# =========================
# 5) تسجيل الدخول
# =========================

def initialize_session_state():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = ""
    if "user" not in st.session_state:
        st.session_state.user = None
    if "page" not in st.session_state:
        st.session_state.page = "Data"


def show_login_screen(users):
    st.markdown("""
        <h1 style='text-align: center; color: #081f37; font-size: 2.5em; font-weight: bold;'>
            مؤسسة الفهــــــــــــد للخدمات الجمركية والملاحيـة
        </h1>
    """, unsafe_allow_html=True)
    set_background(BACK33)
    if not users:
        st.error("لا يوجد مستخدمون. أضف المستخدمين في secrets.toml.")
        return
    names = list(users.keys())
    with st.form("login"):
        username = st.text_input("المستخدم")
        password = st.text_input("كلمة المرور", type="password")
        ok = st.form_submit_button("دخول", type="primary", use_container_width=True)
    if ok:
        if users[username]["password"] == password:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.user = users[username]
            st.rerun()
        else:
            st.error("❌ كلمة المرور غير صحيحة")


# =========================
# 6) التحديث من MTS (رفع ملف)
# =========================

def update_from_mts(uploaded_file, df_office):
    try:
        df_main = pd.read_excel(uploaded_file)
        df2 = df_main.copy()
        rows_with_data = df2.iloc[:, 0].notna()
        df2.loc[rows_with_data, :] = df2.loc[rows_with_data, :].shift(1, axis=1)
        cols_to_drop = [0, 5, 7, 9, 10, 11, 16]
        cols_to_drop = [i for i in cols_to_drop if i < len(df2.columns)]
        df2 = df2.drop(df2.columns[cols_to_drop], axis=1)

        df2 = df2.rename(columns={
            df2.columns[0]: 'رقم الشهادة',
            df2.columns[1]: "رقم ACID",
            df2.columns[2]: 'إسم الشركة',
            df2.columns[3]: 'ساحة الكشف',
            df2.columns[4]: 'ملاحظات',
            df2.columns[6]: 'تاريخ 46',
            df2.columns[7]: 'تاريخ الكشف',
            df2.columns[8]: 'تاريخ الاعتماد',
            df2.columns[9]: "تاريخ السداد",
            df2.columns[10]: "رقم البوليصة",
            df2.columns[11]: 'الحالة'
        })

        df2['رقم الاقرار'] = df2['رقم الشهادة'].copy()
        df2['السنة'] = df2['رقم الشهادة'].astype(str).str.extract(r'(\d{4})-')
        df2['رقم الشهادة'] = df2['رقم الشهادة'].astype(str).str.replace(r'.*-(\d+).*', r'\1', regex=True)
        df2["رقم الشهادة"] = df2["رقم الشهادة"].apply(lambda x: str(int(x)) if pd.notna(x) and float(x).is_integer() else str(x))

        def simple_fix(date_series):
            result = []
            for cell in date_series:
                if pd.isna(cell):
                    result.append(cell)
                else:
                    cell_str = str(cell).strip()
                    if '/' in cell_str:
                        result.append(cell_str)
                    elif '-' in cell_str:
                        try:
                            dt = pd.to_datetime(cell_str)
                            if ':' in cell_str:
                                result.append(dt.strftime('%m/%d/%Y %H:%M'))
                            else:
                                result.append(dt.strftime('%m/%d/%Y'))
                        except Exception:
                            result.append(cell_str)
                    else:
                        result.append(cell_str)
            return result

        df2['تاريخ 46'] = simple_fix(df2['تاريخ 46'])
        df2['تاريخ الكشف'] = simple_fix(df2['تاريخ الكشف'])
        df2['تاريخ الاعتماد'] = simple_fix(df2['تاريخ الاعتماد'])
        df2["تاريخ السداد"] = simple_fix(df2["تاريخ السداد"])
        df2['تاريخ الكشف'] = pd.to_datetime(df2['تاريخ الكشف'], errors='coerce', dayfirst=True)
        df2['تاريخ الاعتماد'] = pd.to_datetime(df2['تاريخ الاعتماد'], errors='coerce', dayfirst=True)
        df2['تاريخ 46'] = pd.to_datetime(df2['تاريخ 46'], errors='coerce', dayfirst=True)
        df2["تاريخ السداد"] = pd.to_datetime(df2["تاريخ السداد"], errors='coerce', dayfirst=True)

        col = df2.iloc[:, 5].astype(str)
        df2['طلب فحص واردات'] = col.str.extract(r'وارد صناعي (\d+)/\d+')
        df2['طلب سلامة غذاء'] = col.str.extract(r'وارد غذائي [^\d]*(\d+)')
        df2['دمغة وموازين'] = col.str.extract(r'دمغة.*?(\d+)/\d+')

        if 'السنة' not in df_office.columns:
            df_office.insert(23, 'السنة', '')
        if 'رقم الاقرار' not in df_office.columns:
            df_office['رقم الاقرار'] = ''

        df2['cert_clean'] = df2['رقم الشهادة'].astype(str).str.extract(r'(\d+)')

        for _, row in df2.iterrows():
            mask = df_office["رقم ACID"] == row["رقم ACID"]
            if mask.any():
                if pd.notna(row['طلب فحص واردات']):
                    df_office.loc[mask, 'طلب فحص واردات'] = row['طلب فحص واردات']
                if pd.notna(row['طلب سلامة غذاء']):
                    df_office.loc[mask, 'طلب سلامة غذاء'] = row['طلب سلامة غذاء']
                if pd.notna(row['دمغة وموازين']):
                    df_office.loc[mask, 'دمغة وموازين'] = row['دمغة وموازين']
                if pd.notna(row["رقم البوليصة"]):
                    df_office.loc[mask, "رقم البوليصة"] = row["رقم البوليصة"]
                df_office.loc[mask, 'الحالة'] = row['الحالة']
                df_office.loc[mask, 'رقم الشهادة'] = row['رقم الشهادة']
                df_office.loc[mask, 'رقم الاقرار'] = row['رقم الاقرار']
                df_office.loc[mask, 'إسم الشركة'] = row['إسم الشركة']
                df_office.loc[mask, 'ساحة الكشف'] = row['ساحة الكشف']
                df_office.loc[mask, 'ملاحظات'] = row['ملاحظات']
                df_office.loc[mask, 'تاريخ الكشف'] = row['تاريخ الكشف']
                df_office.loc[mask, "تاريخ السداد"] = row["تاريخ السداد"]
                df_office.loc[mask, 'تاريخ الاعتماد'] = row['تاريخ الاعتماد']
                df_office.loc[mask, 'تاريخ 46'] = row['تاريخ 46']
                df_office.loc[mask, 'السنة'] = row['السنة']

        df2.drop(columns=['cert_clean'], inplace=True)
        df_office['تاريخ الكشف'] = pd.to_datetime(df_office['تاريخ الكشف'], errors='coerce')
        df_office["تاريخ السداد"] = pd.to_datetime(df_office["تاريخ السداد"], errors='coerce')
        df_office['تاريخ 46'] = pd.to_datetime(df_office['تاريخ 46'], errors='coerce')
        df_office['تاريخ الاعتماد'] = pd.to_datetime(df_office['تاريخ الاعتماد'], errors='coerce')
        df_office["رقم الشهادة"] = df_office["رقم الشهادة"].apply(lambda x: str(int(float(x))) if pd.notna(x) and str(x).strip() != "" else "")

        new_rows = []
        for _, row in df2.iterrows():
            acid = row["رقم ACID"]
            if not df_office["رقم ACID"].isin([acid]).any():
                new_row = {
                    'رقم الشهادة': row['رقم الشهادة'],
                    'رقم الاقرار': row['رقم الاقرار'],
                    'رقم ACID': acid,
                    'إسم الشركة': row['إسم الشركة'],
                    'ساحة الكشف': row['ساحة الكشف'],
                    'ملاحظات': row['ملاحظات'],
                    'تاريخ 46': row['تاريخ 46'],
                    'تاريخ الكشف': row['تاريخ الكشف'],
                    'تاريخ الاعتماد': row['تاريخ الاعتماد'],
                    'تاريخ السداد': row['تاريخ السداد'],
                    'رقم البوليصة': row['رقم البوليصة'],
                    'الحالة': row['الحالة'],
                    'طلب فحص واردات': row['طلب فحص واردات'],
                    'طلب سلامة غذاء': row['طلب سلامة غذاء'],
                    'دمغة وموازين': row['دمغة وموازين'],
                    'السنة': row['السنة']
                }
                new_rows.append(new_row)

        if new_rows:
            df_new = pd.DataFrame(new_rows)
            df_office = pd.concat([df_office, df_new], ignore_index=True)

        save_data(df_office)
        st.session_state.df = df_office
        st.success("تم التحديث من ملف MTS وحفظه في Google Sheets ✅")
        st.rerun()
    except Exception as e:
        st.error(f"خطأ في التحديث من MTS: {e}")


# =========================
# 7) إضافة شهادة جديدة
# =========================

def add_new_certificate(df, sorted_companies, sorted_authorizations):
    if not can_edit(st.session_state.user):
        st.warning("حسابك للقراءة فقط — لا يمكنك إضافة شهادات")
        return
    st.title("Add New Certificate")
    st.badge("New")

    if "custom_company_mode" not in st.session_state:
        st.session_state.custom_company_mode = False
    if "custom_authorization_mode" not in st.session_state:
        st.session_state.custom_authorization_mode = False

    col1, col2, col3 = st.columns([6, 6, 1])
    with col3:
        if st.button("➕", key="toggle_custom_company", type="secondary"):
            st.session_state.custom_company_mode = not st.session_state.custom_company_mode
            st.rerun()
    with col2:
        if st.session_state.custom_company_mode:
            company_name = st.text_input("إسم الشركة (جديد)", key="custom_company_input")
        else:
            company_name = st.selectbox(" الشركة", sorted_companies, key="select_company")
    with col1:
        if not df.empty and company_name in df["إسم الشركة"].values:
            latest_row = df[df["إسم الشركة"] == company_name].iloc[-1]
            acid_value_12 = str(latest_row["رقم ACID"])[:12] if pd.notna(latest_row["رقم ACID"]) else ""
            acid = st.text_input(" ACID ", value=acid_value_12, max_chars=19)
        else:
            acid = st.text_input(" ACID ", max_chars=19)

    col1, col2, col3, col4 = st.columns([7, 3, 1, 7])
    with col1:
        paper_received = st.date_input("تاريخ إستلام الورق", value=None)
    with col3:
        if st.button("➕", key="toggle_custom_auth", type="secondary"):
            st.session_state.custom_authorization_mode = not st.session_state.custom_authorization_mode
            st.rerun()
    with col2:
        if st.session_state.custom_authorization_mode:
            authorization = st.text_input("التوكيل (جديد)", key="custom_auth_input")
        else:
            authorization = st.selectbox("التوكيل", sorted_authorizations, key="select_auth")
    with col4:
        bl_number = st.text_input("رقم البوليصة")

    col1, col2, col3_1, col3_2 = st.columns([2, 1, 1, 1])
    with col1:
        item_type = st.text_input("الصنف")
    with col2:
        quantity = st.number_input("العدد", min_value=0)
    with col3_1:
        container_20 = st.number_input("عدد الحاويات 20", min_value=0)
    with col3_2:
        container_40 = st.number_input("عدد الحاويات 40", min_value=0)

    col1, col2 = st.columns(2)
    with col1:
        port_of_loading = st.text_input("ميناء الشحن")
    with col2:
        country_of_origin = st.text_input("دولة المنشأ")

    col1, col2 = st.columns(2)
    with col1:
        cont_col, btn_cont_col = st.columns([4, 1])
        with btn_cont_col:
            if st.button("➕", key="add_new_container_btn", type="secondary", help="إضافة حاوية أخرى"):
                if "new_container_numbers" not in st.session_state:
                    st.session_state.new_container_numbers = [""]
                else:
                    st.session_state.new_container_numbers.append("")
                st.rerun()
        with cont_col:
            st.markdown("**رقم الحاوية**")
            if "new_container_numbers" not in st.session_state or not st.session_state.new_container_numbers:
                st.session_state.new_container_numbers = [""]
            for i in range(len(st.session_state.new_container_numbers)):
                key_cont = f"new_container_number_{i}"
                val = st.text_input(f"حاوية #{i+1}", key=key_cont)
                st.session_state.new_container_numbers[i] = val
            if len(st.session_state.new_container_numbers) > 1:
                if st.button("🗑️ حذف آخر حاوية", key="remove_new_last_container", type="secondary"):
                    st.session_state.new_container_numbers.pop()
                    st.rerun()
    with col2:
        date_arrival = st.date_input("التاريخ المتوقع الوصول", value=None)

    notes = st.text_area("ملاحظات", height=100)

    save = st.button("Save 💾", type="primary")
    if save:
        save_new_certificate(company_name, acid, paper_received, authorization, bl_number,
                             item_type, quantity, container_20, container_40, date_arrival, notes,
                             port_of_loading, country_of_origin, df)


def save_new_certificate(company_name, acid, paper_received, authorization, bl_number,
                         item_type, quantity, container_20, container_40, date_arrival, notes,
                         port_of_loading, country_of_origin, df):
    if not acid or acid.strip() == "":
        st.warning("يرجى إدخال رقم ACID.")
        return
    if not df.empty and acid in df["رقم ACID"].astype(str).values:
        st.error(f"ACID '{acid}' is already here ! ")
        return
    if not df.empty and bl_number and bl_number.strip() != "":
        if bl_number in df["رقم البوليصة"].astype(str).values:
            st.error(f"رقم البوليصة '{bl_number}' موجود بالفعل ! ")
            return

    container_numbers_list = []
    if "new_container_numbers" in st.session_state:
        container_numbers_list = [x.strip() for x in st.session_state.new_container_numbers if x.strip()]
    container_number_str = "; ".join(container_numbers_list) if container_numbers_list else ""

    new_row = {
        "إسم الشركة": company_name,
        "رقم ACID": acid,
        "تاريخ إستلام الورق": paper_received,
        "التوكيل": authorization,
        "رقم البوليصة": bl_number,
        "الصنف": item_type,
        "العدد": quantity,
        "رقم الحاوية": container_number_str,
        "عدد الحاويات": f"20X{int(container_20)} + 40X{int(container_40)}",
        "رقم الشهادة": "",
        "رقم الاقرار": "",
        "تاريخ 46": "",
        "طلب فحص واردات": "",
        "طلب سلامة غذاء": "",
        "دمغة وموازين": "",
        "تاريخ الكشف": "",
        "تاريخ الاعتماد": "",
        "تاريخ السداد": "",
        "ملاحظات": notes,
        "الحالة": "",
        "التاريخ المتوقع الوصول": date_arrival,
        "تاريخ الوصول الفعلي": "",
        "تاريخ السماح": "",
        "قيمة الفاتورة": "",
        "ميناء الشحن": port_of_loading,
        "دولة المنشأ": country_of_origin
    }

    new_row_df = pd.DataFrame([new_row])
    df_current = df.dropna(axis=1, how='all') if not df.empty else df
    new_row_df = new_row_df.dropna(axis=1, how='all')

    if not df_current.empty:
        new_row_df = new_row_df.reindex(columns=df_current.columns, fill_value=None)

    df_updated = pd.concat([df_current, new_row_df], ignore_index=True) if not df_current.empty else new_row_df

    try:
        save_data(df_updated)
        st.session_state.df = df_updated
        if "custom_company_mode" in st.session_state:
            st.session_state.custom_company_mode = False
        if "custom_authorization_mode" in st.session_state:
            st.session_state.custom_authorization_mode = False
        if "new_container_numbers" in st.session_state:
            del st.session_state.new_container_numbers
        st.success("تم الحفظ في Google Sheets بنجاح! ✅")
        st.rerun()
    except Exception as e:
        st.error(f"خطأ في الحفظ: {e}")


# =========================
# 8) عرض وتعديل شهادة
# =========================

def display_certificate_form(selected_row, df, sorted_companies, sorted_authorizations):
    if "edit_custom_authorization_mode" not in st.session_state:
        st.session_state.edit_custom_authorization_mode = False

    if not isinstance(selected_row, dict):
        selected_row = selected_row.to_dict()
    for _k in list(selected_row.keys()):
        if pd.isna(selected_row[_k]):
            selected_row[_k] = ""

    cert_key = f"invoice_values_{selected_row.get('رقم ACID', 'unknown')}"
    if "current_cert_key" not in st.session_state or st.session_state.current_cert_key != cert_key or "edit_invoice_values" not in st.session_state:
        st.session_state.current_cert_key = cert_key
        raw_inv = selected_row.get("قيمة الفاتورة")
        if pd.notna(raw_inv) and str(raw_inv).strip() != "" and str(raw_inv).strip() != "nan":
            if ";" in str(raw_inv):
                st.session_state.edit_invoice_values = [float(x.strip()) for x in str(raw_inv).split(";") if x.strip()]
            else:
                try:
                    st.session_state.edit_invoice_values = [float(raw_inv)]
                except Exception:
                    st.session_state.edit_invoice_values = []
        else:
            st.session_state.edit_invoice_values = []

    container_key = f"container_values_{selected_row.get('رقم ACID', 'unknown')}"
    if "current_container_key" not in st.session_state or st.session_state.current_container_key != container_key or "edit_container_numbers" not in st.session_state:
        st.session_state.current_container_key = container_key
        raw_container = selected_row.get("رقم الحاوية")
        if pd.notna(raw_container) and str(raw_container).strip() != "" and str(raw_container).strip() != "nan":
            if ";" in str(raw_container):
                st.session_state.edit_container_numbers = [x.strip() for x in str(raw_container).split(";") if x.strip()]
            else:
                st.session_state.edit_container_numbers = [str(raw_container)]
        else:
            st.session_state.edit_container_numbers = []

    col1, col2 = st.columns(2)
    with col1:
        status_options = df['الحالة'].dropna().astype(str).unique().tolist() if not df.empty and 'الحالة' in df.columns else []
        current_value = selected_row.get("الحالة", None)
        if pd.isna(current_value) or str(current_value).strip() == "":
            default_index = 0
        elif str(current_value) in status_options:
            default_index = status_options.index(str(current_value))
        else:
            default_index = 0
        st.selectbox("الحالة", options=status_options, index=default_index, key="edit_current_status")

    col1, col2, col3 = st.columns(3)
    with col1:
        cert_number_val = selected_row.get("رقم الشهادة")
        if pd.notna(cert_number_val):
            try:
                cert_number_val = str(int(float(cert_number_val)))
            except Exception:
                cert_number_val = str(cert_number_val)
        else:
            cert_number_val = ""
        st.text_input("رقم الشهادة", value=cert_number_val, key="edit_cert_number")
    with col2:
        st.text_input("ACID", value=str(selected_row["رقم ACID"]), key="edit_acid")
    with col3:
        default_index = sorted_companies.index(selected_row["إسم الشركة"]) if selected_row["إسم الشركة"] in sorted_companies else 0
        st.selectbox(" الشركة", sorted_companies, index=default_index, key="edit_company_name")

    col1, col2, col3 = st.columns(3)
    with col3:
        st.date_input("تاريخ إستلام الورق", value=safe_date(selected_row.get("تاريخ إستلام الورق")), key="edit_paper_received")
    with col2:
        inp_col, btn_col = st.columns([4, 1])
        with btn_col:
            if st.button("➕", key="toggle_edit_custom_auth", type="secondary", help="إضافة توكيل جديد"):
                st.session_state.edit_custom_authorization_mode = not st.session_state.edit_custom_authorization_mode
                st.rerun()
        with inp_col:
            default_value = selected_row.get("التوكيل", "None")
            try:
                default_index = sorted_authorizations.index(default_value) if default_value in sorted_authorizations else 0
            except ValueError:
                default_index = 0
            if st.session_state.edit_custom_authorization_mode:
                st.text_input("التوكيل", value=default_value, key="edit_authorization", placeholder="أكتب اسم التوكيل")
            else:
                st.selectbox("التوكيل", sorted_authorizations, index=default_index, key="edit_authorization")
    with col1:
        st.text_input("رقم البوليصة", value=selected_row.get("رقم البوليصة", ""), key="edit_bl_number")

    col1, col2, col3_1, col3_2 = st.columns([2, 1, 1, 1])
    with col1:
        st.text_input("الصنف", value=selected_row.get("الصنف", ""), key="edit_item_type")
    with col2:
        quantity_val = selected_row.get("العدد", 0)
        try:
            quantity_val = 0 if pd.isna(quantity_val) else int(float(quantity_val))
        except Exception:
            quantity_val = 0
        st.number_input("العدد", min_value=0, value=quantity_val, key="edit_quantity")
    containers_str = str(selected_row.get("عدد الحاويات", ""))
    matches_20 = re.findall(r"20[xX](\d+)", containers_str)
    matches_40 = re.findall(r"40[xX](\d+)", containers_str)
    container_20_val = int(matches_20[0]) if matches_20 else 0
    container_40_val = int(matches_40[0]) if matches_40 else 0
    with col3_1:
        st.number_input("عدد الحاويات 20", min_value=0, value=container_20_val, key="edit_container_20")
    with col3_2:
        st.number_input("عدد الحاويات 40", min_value=0, value=container_40_val, key="edit_container_40")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input("طلب فحص واردات", value=selected_row.get("طلب فحص واردات", ""), key="edit_inspection_import")
    with col2:
        st.text_input("طلب سلامة غذاء", value=selected_row.get("طلب سلامة غذاء", ""), key="edit_food_safety")
    with col3:
        st.text_input("دمغة وموازين", value=selected_row.get("دمغة وموازين", ""), key="edit_stamping_scales")

    colk1, colk2, colk3 = st.columns(3)
    with colk1:
        st.date_input("تاريخ الكشف", value=safe_date(selected_row.get("تاريخ الكشف")), key="edit_inspection_date")
    with colk2:
        st.date_input("التاريخ المتوقع الوصول", value=safe_date(selected_row.get("التاريخ المتوقع الوصول")), key="edit_date_arrival")
    with colk3:
        st.date_input("تاريخ 46", value=safe_date(selected_row.get("تاريخ 46")), key="edit_date_46")

    col_new1, col_new2, col_new3 = st.columns(3)
    with col_new1:
        st.date_input("تاريخ الوصول الفعلي", value=safe_date(selected_row.get("تاريخ الوصول الفعلي")), key="edit_actual_arrival")
    with col_new2:
        st.date_input("تاريخ السماح", value=safe_date(selected_row.get("تاريخ السماح")), key="edit_permission_date")
    with col_new3:
        inv_col, btn_inv_col = st.columns([4, 1])
        with btn_inv_col:
            if st.button("➕", key="add_invoice_btn", type="secondary", help="إضافة فاتورة أخرى"):
                if "edit_invoice_values" not in st.session_state:
                    st.session_state.edit_invoice_values = [0.0]
                else:
                    st.session_state.edit_invoice_values.append(0.0)
                st.rerun()
        with inv_col:
            st.markdown("**قيمة الفاتورة**")
            if "edit_invoice_values" not in st.session_state or not st.session_state.edit_invoice_values:
                st.session_state.edit_invoice_values = [0.0]
            for i, val in enumerate(st.session_state.edit_invoice_values):
                key_inv = f"edit_invoice_value_{i}"
                st.number_input(f"فاتورة #{i+1}", min_value=0.0, step=0.1, value=float(val) if val else 0.0, key=key_inv, label_visibility="collapsed")
            if len(st.session_state.edit_invoice_values) > 1:
                if st.button("🗑️ حذف آخر فاتورة", key="remove_last_invoice", type="secondary"):
                    st.session_state.edit_invoice_values.pop()
                    st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        st.text_input("ميناء الشحن", value=selected_row.get("ميناء الشحن", ""), key="edit_port_of_loading")
    with col2:
        st.text_input("دولة المنشأ", value=selected_row.get("دولة المنشأ", ""), key="edit_country_of_origin")

    colk1, colk2 = st.columns(2)
    with colk1:
        cont_col, btn_cont_col = st.columns([4, 1])
        with btn_cont_col:
            if st.button("➕", key="add_container_btn", type="secondary", help="إضافة حاوية أخرى"):
                if "edit_container_numbers" not in st.session_state:
                    st.session_state.edit_container_numbers = [""]
                else:
                    st.session_state.edit_container_numbers.append("")
                st.rerun()
        with cont_col:
            st.markdown("**رقم الحاوية**")
            if "edit_container_numbers" not in st.session_state or not st.session_state.edit_container_numbers:
                st.session_state.edit_container_numbers = [""]
            for i, val in enumerate(st.session_state.edit_container_numbers):
                key_cont = f"edit_container_number_{i}"
                st.text_input(f"حاوية #{i+1}", value=val if val else "", key=key_cont, label_visibility="collapsed")
            if len(st.session_state.edit_container_numbers) > 1:
                if st.button("🗑️ حذف آخر حاوية", key="remove_last_container", type="secondary"):
                    st.session_state.edit_container_numbers.pop()
                    st.rerun()
    with colk2:
        st.text_input("ساحة الكشف", value=selected_row.get("ساحة الكشف", ""), key="edit_area")

    st.text_area("ملاحظات", height=100, value=selected_row.get("ملاحظات", ""), key="edit_notes")


def save_certificate_changes(selected_row):
    try:
        df = st.session_state.df
        row_index = selected_row.name

        cert_number = st.session_state.get("edit_cert_number", "")
        acid = st.session_state.get("edit_acid", "")
        company_name = st.session_state.get("edit_company_name", "")
        paper_received = st.session_state.get("edit_paper_received", None)
        authorization = st.session_state.get("edit_authorization", "")
        bl_number = st.session_state.get("edit_bl_number", "")
        item_type = st.session_state.get("edit_item_type", "")
        quantity = st.session_state.get("edit_quantity", 0)
        container_20 = st.session_state.get("edit_container_20", 0)
        container_40 = st.session_state.get("edit_container_40", 0)
        inspection_import = st.session_state.get("edit_inspection_import", "")
        food_safety = st.session_state.get("edit_food_safety", "")
        stamping_scales = st.session_state.get("edit_stamping_scales", "")
        inspection_date = st.session_state.get("edit_inspection_date", None)
        date_arrival = st.session_state.get("edit_date_arrival", None)
        date_46 = st.session_state.get("edit_date_46", None)
        actual_arrival = st.session_state.get("edit_actual_arrival", None)
        permission_date = st.session_state.get("edit_permission_date", None)

        invoice_values_list = []
        i = 0
        while True:
            key = f"edit_invoice_value_{i}"
            if key in st.session_state:
                invoice_values_list.append(st.session_state[key])
                i += 1
            else:
                break
        invoice_value_str = "; ".join([f"{v:.2f}" for v in invoice_values_list]) if invoice_values_list else ""

        container_numbers_list = []
        i = 0
        while True:
            key = f"edit_container_number_{i}"
            if key in st.session_state:
                val = st.session_state[key]
                if str(val).strip():
                    container_numbers_list.append(str(val).strip())
                i += 1
            else:
                break
        container_number_str = "; ".join(container_numbers_list) if container_numbers_list else ""

        port_of_loading = st.session_state.get("edit_port_of_loading", "")
        country_of_origin = st.session_state.get("edit_country_of_origin", "")
        current_status = st.session_state.get("edit_current_status", "")
        area = st.session_state.get("edit_area", "")
        notes = st.session_state.get("edit_notes", "")

        df.loc[row_index] = {
            "إسم الشركة": company_name,
            "رقم ACID": acid,
            "تاريخ إستلام الورق": paper_received,
            "التوكيل": authorization,
            "رقم البوليصة": bl_number,
            "الصنف": item_type,
            "العدد": quantity,
            "ميناء الشحن": port_of_loading,
            "دولة المنشأ": country_of_origin,
            "عدد الحاويات": f"20X{int(container_20)} + 40X{int(container_40)}",
            "رقم الشهادة": cert_number,
            "رقم الاقرار": selected_row.get("رقم الاقرار", ""),
            "تاريخ 46": date_46,
            "طلب فحص واردات": inspection_import,
            "طلب سلامة غذاء": food_safety,
            "دمغة وموازين": stamping_scales,
            "ساحة الكشف": area,
            "تاريخ الكشف": inspection_date,
            "تاريخ الاعتماد": selected_row.get("تاريخ الاعتماد"),
            "تاريخ السداد": selected_row.get("تاريخ السداد"),
            "ملاحظات": notes,
            "الحالة": current_status,
            "التاريخ المتوقع الوصول": date_arrival,
            "تاريخ الوصول الفعلي": actual_arrival,
            "تاريخ السماح": permission_date,
            "قيمة الفاتورة": invoice_value_str,
            "رقم الحاوية": container_number_str,
        }

        save_data(df)
        st.session_state.df = df
        st.success("تم حفظ التعديلات في Google Sheets ✅")

        if "edit_custom_authorization_mode" in st.session_state:
            st.session_state.edit_custom_authorization_mode = False
        delete_keys = [k for k in list(st.session_state.keys()) if k.startswith("edit_invoice_value_") or k.startswith("edit_container_number_") or k in ("edit_invoice_values", "edit_container_numbers")]
        for k in delete_keys:
            del st.session_state[k]
        st.rerun()
    except Exception as e:
        st.error(f"خطأ في الحفظ: {e}")


def show_certificate_details(selected_row):
    st.title("بيانات الشهادة")
    set_background(BACK22)
    if st.button("⬅ Back"):
        st.session_state.page = 'Data'
        st.rerun()

    df = st.session_state.df
    sorted_companies = get_sorted_companies(df)
    sorted_authorizations = get_sorted_authorizations(df)

    row_df = pd.DataFrame([selected_row]).reset_index(drop=True)
    st.download_button(
        "⬇️ تحميل بيانات الشهادة Excel",
        data=to_excel_bytes(row_df),
        file_name="شهادة.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if can_edit(st.session_state.user):
        display_certificate_form(selected_row, df, sorted_companies, sorted_authorizations)
        if st.button("Save 💾", type="primary"):
            save_certificate_changes(selected_row)
    else:
        st.info("🔒 أنت في وضع القراءة فقط — لا يمكنك تعديل هذا السجل")
        st.dataframe(row_df, use_container_width=True, hide_index=True)

    if is_admin(st.session_state.user):
        st.markdown("---")
        with st.expander("🗑️ حذف السجل"):
            st.warning("⚠️ سيتم حذف هذا السجل نهائيًا من Google Sheets.")
            if st.checkbox("تأكيد الحذف"):
                if st.button("حذف نهائي"):
                    df = st.session_state.df
                    df = df.drop(index=selected_row.name).reset_index(drop=True)
                    save_data(df)
                    st.session_state.df = df
                    st.session_state.page = 'Data'
                    st.success("تم حذف السجل ✅")
                    st.rerun()


# =========================
# 9) البحث والفلترة وعرض البيانات
# =========================

def show_search_interface(df):
    PAGE = "view_data"
    columns = df.columns.tolist() if not df.empty else []
    important_columns = ["رقم الشهادة", "رقم ACID", "إسم الشركة", "رقم البوليصة", "الحالة", "التاريخ المتوقع الوصول", "تاريخ الكشف", "حالات جاريه", "انتظار وصول"]
    date_columns = ["تاريخ إستلام الورق", "تاريخ 46", "تاريخ الكشف", "التاريخ المتوقع الوصول", "تاريخ السداد", "تاريخ الاعتماد", "تاريخ الوصول الفعلي", "تاريخ السماح"]
    virtual_filters = ["حالات جاريه", "انتظار وصول"]
    additional_columns = [col for col in columns if col not in important_columns]

    input_mapping = {
        "رقم ACID": "text", "إسم الشركة": "select", "تاريخ إستلام الورق": "date",
        "التوكيل": "select", "رقم البوليصة": "text", "الصنف": "text",
        "العدد": "number", "عدد الحاويات 20": "number", "عدد الحاويات 40": "number",
        "رقم الشهادة": "text", "تاريخ 46": "date", "طلب فحص واردات": "text",
        "طلب سلامة غذاء": "text", "دمغة وموازين": "text", "تاريخ الكشف": "date",
        "التاريخ المتوقع الوصول": "date", "تاريخ السداد": "date", "تاريخ الاعتماد": "date",
        "الحالة": "select", "ملاحظات": "textarea", "ساحة الكشف": "select"
    }

    search_values = {}

    def render_search_field(col, input_type, container):
        with container:
            chk_key = f"{PAGE}_chk_{col}"
            checked = st.checkbox(col, value=False, key=chk_key)
            if checked:
                if col in virtual_filters:
                    search_values[col] = True
                else:
                    is_date_range_mode = False
                    if col in date_columns:
                        state_key = f"{PAGE}_range_state_{col}"
                        btn_key = f"{PAGE}_range_btn_{col}"
                        if state_key not in st.session_state:
                            st.session_state[state_key] = False
                        col_chk, col_range = st.columns([5, 1])
                        with col_range:
                            if st.button("➕", key=btn_key, help="بحث بنطاق زمني (من - إلى)", type="secondary"):
                                st.session_state[state_key] = not st.session_state[state_key]
                                st.rerun()
                        is_date_range_mode = st.session_state[state_key]
                    search_values[col] = get_search_input(col, input_type, df, PAGE, is_range_mode=is_date_range_mode)

    for i in range(0, len(important_columns), 3):
        cols = st.columns(3)
        for j, col in enumerate(important_columns[i:i+3]):
            if col in columns or col in virtual_filters:
                render_search_field(col, input_mapping.get(col, "text"), cols[j])

    show_additional = st.checkbox("🔍 خيارات بحث إضافية", key=f"{PAGE}_show_additional")
    if show_additional:
        st.markdown("### 📋 الخيارات الإضافية")
        for i in range(0, len(additional_columns), 3):
            cols = st.columns(3)
            for j, col in enumerate(additional_columns[i:i+3]):
                if col in columns:
                    render_search_field(col, input_mapping.get(col, "text"), cols[j])

    return search_values


def get_search_input(col, input_type, df, page, is_range_mode=False):
    key_base = f"{page}_search_{col}"
    if col == "ساحة الكشف":
        options = df[col].dropna().unique().tolist()
        return st.selectbox("", options, key=key_base) if options else ""
    if input_type == "select":
        options = df[col].dropna().unique().tolist()
        return st.selectbox("", options, key=key_base) if options else None
    if input_type == "text":
        return st.text_input("", key=key_base)
    if input_type == "number":
        return st.number_input("", min_value=0, value=0, key=key_base)
    if input_type == "date":
        if is_range_mode:
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("من", value=None, key=f"{key_base}_start")
            with col2:
                end_date = st.date_input("إلى", value=None, key=f"{key_base}_end")
            return (start_date, end_date)
        else:
            return st.date_input("", value=None, key=key_base)
    return st.text_area("", key=key_base)


def filter_dataframe(df, search_values):
    filtered_df = df.copy().sort_index(ascending=False)
    if search_values.get("حالات جاريه"):
        excluded_statuses = ['مـٌعَلـَق', 'منتهى', 'تحت التسوية', 'جارى تسليم الإفراج']
        if 'الحالة' in filtered_df.columns:
            status_col = filtered_df['الحالة'].astype(str).str.strip()
            mask_active = (filtered_df['الحالة'].notna()) & (status_col != '') & (~status_col.isin(excluded_statuses))
            filtered_df = filtered_df[mask_active]
    if search_values.get("انتظار وصول"):
        required_cols = ['ساحة الكشف', 'تاريخ إستلام الورق', 'رقم ACID', 'الحالة']
        if all(col in filtered_df.columns for col in required_cols):
            mask_waiting = (
                (filtered_df['ساحة الكشف'].isna() | (filtered_df['ساحة الكشف'].astype(str).str.strip() == '')) &
                (filtered_df['تاريخ إستلام الورق'].notna()) &
                (filtered_df["رقم ACID"].notna()) &
                (~filtered_df['الحالة'].astype(str).str.strip().isin(['منتهى', 'مُعَلَّق']))
            )
            filtered_df = filtered_df[mask_waiting]

    for col, val in search_values.items():
        if col in ["حالات جاريه", "انتظار وصول"] or val is None:
            continue
        if isinstance(val, tuple) and len(val) == 2:
            start_date, end_date = val
            if start_date is None and end_date is None:
                continue
            if col not in filtered_df.columns:
                continue
            try:
                col_dates = pd.to_datetime(filtered_df[col], errors='coerce').dt.date
                mask = pd.Series([True] * len(filtered_df), index=filtered_df.index)
                if start_date:
                    mask = mask & (col_dates >= start_date)
                if end_date:
                    mask = mask & (col_dates <= end_date)
                filtered_df = filtered_df[mask]
            except Exception as e:
                st.warning(f"خطأ في فلترة التاريخ {col}: {e}")
            continue
        if val not in ["", 0]:
            input_type = {
                "رقم ACID": "text", "إسم الشركة": "select", "تاريخ إستلام الورق": "date",
                "التوكيل": "select", "رقم البوليصة": "text", "الصنف": "text",
                "العدد": "number", "عدد الحاويات 20": "number", "عدد الحاويات 40": "number",
                "رقم الشهادة": "text", "تاريخ 46": "date", "طلب فحص واردات": "text",
                "طلب سلامة غذاء": "text", "دمغة وموازين": "text", "تاريخ الكشف": "date",
                "التاريخ المتوقع الوصول": "date", "تاريخ السداد": "date", "تاريخ الاعتماد": "date",
                "الحالة": "select", "ملاحظات": "textarea", "ساحة الكشف": "select"
            }.get(col, "text")
            if col not in filtered_df.columns:
                continue
            if input_type == "date":
                try:
                    col_dates = pd.to_datetime(filtered_df[col], errors='coerce').dt.date
                    search_date = val
                    if isinstance(val, str):
                        try:
                            search_date = pd.to_datetime(val).date()
                        except Exception:
                            pass
                    filtered_df = filtered_df[col_dates == search_date]
                except Exception:
                    pass
            elif col == "رقم الشهادة":
                filtered_df = filtered_df[filtered_df[col].astype(str).str.strip() == str(val).strip()]
            elif col == "رقم البوليصة":
                cell_values = filtered_df[col].astype(str).str.lower().str.strip()
                search_val = str(val).lower().strip()
                filtered_df = filtered_df[cell_values.str.contains(search_val, na=False)]
            else:
                cell_values = filtered_df[col].astype(str).str.lower().str.strip()
                search_val = str(val).lower().strip()
                filtered_df = filtered_df[cell_values.str.contains(search_val, na=False, regex=False)]
    return filtered_df


def show_data_table(df, search_values):
    filtered_df = filter_dataframe(df, search_values)
    st.session_state.current_display_df = filtered_df.reset_index(drop=True)

    def zebra_stripes(row):
        if row.name % 2 == 0:
            return ['background-color: #ceefff;' for _ in row]
        else:
            return ['background-color: #ffffff;' for _ in row]

    styled_df = filtered_df.style.apply(zebra_stripes, axis=1).set_properties(**{'text-align': 'center'})

    column_config = {
        "إسم الشركة": st.column_config.Column(pinned=True),
        "رقم ACID": st.column_config.Column(pinned=True),
        "رقم الشهادة": st.column_config.Column(pinned=True),
        "الحالة": st.column_config.Column(pinned=True, width=120),
        "قيمة الفاتورة": st.column_config.TextColumn("قيمة الفاتورة (USD)"),
        "رقم الحاوية": st.column_config.TextColumn("رقم الحاوية", width=200),
        "تاريخ إستلام الورق": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "تاريخ 46": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm a", width=130),
        "تاريخ الكشف": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "التاريخ المتوقع الوصول": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "تاريخ السداد": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "تاريخ الاعتماد": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "تاريخ الوصول الفعلي": st.column_config.DateColumn(format="YYYY-MM-DD", width="fit"),
        "ساحة الكشف": st.column_config.Column(width=170),
        "رقم البوليصة": st.column_config.Column(width=150),
    }

    if len(filtered_df) < 15:
        pick = st.dataframe(styled_df, use_container_width=True, height=480, on_select="rerun", selection_mode="single-row", column_config=column_config)
    else:
        pick = st.dataframe(styled_df, use_container_width=True, height=550, on_select="rerun", selection_mode="single-row", column_config=column_config)

    st.markdown("""
        <style>
        div[data-testid="stDataFrame"] {
            border: 3px solid #ffffff !important;
            border-radius: 15px !important;
            overflow: hidden !important;
            margin-bottom: 0px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    if "show_export_columns" not in st.session_state:
        st.session_state.show_export_columns = False
    if "selected_columns" not in st.session_state:
        st.session_state.selected_columns = []

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 export report", key="export_report_main"):
            st.session_state.show_export_columns = True
            st.session_state.selected_columns = []
            st.rerun()
    with col2:
        if st.session_state.show_export_columns:
            if st.button("🚫 إلغاء", key="cancel_export", type="secondary"):
                st.session_state.show_export_columns = False
                st.session_state.selected_columns = []
                st.rerun()
            if st.button("🚀 export now", key="export_now_final", type="primary"):
                if st.session_state.selected_columns:
                    export_df = st.session_state.get("current_display_df", filtered_df)
                    html_filtered = """
                    <!DOCTYPE html>
                    <html lang="ar" dir="rtl">
                    <head>
                    <meta charset="UTF-8">
                    <title>تقرير مخصص</title>
                    <style>
                    body { font-family: Arial; background: #f4f6f7; padding: 30px; }
                    .company { text-align: center; font-size: 32px; font-weight: bold; color: darkblue; margin-bottom: 40px; }
                    table { width: 100%; border-collapse: collapse; background: white; }
                    th { background: #dff9fb; padding: 8px; border: 1px solid #ccc; }
                    td { padding: 8px; border: 1px solid #ddd; text-align: center; }
                    </style>
                    </head>
                    <body>
                    <div class="company">مؤسسة الفهد للخدمات الملاحية و الجمركية</div>
                    <h2 style="text-align:center; color:darkred;">تقرير مخصص</h2>
                    <table><tr>
                    """
                    for h in st.session_state.selected_columns:
                        html_filtered += f"<th>{h}</th>"
                    html_filtered += "</tr>"
                    for _, r in export_df.iterrows():
                        html_filtered += "<tr>"
                        for h in st.session_state.selected_columns:
                            value = r.get(h, '_____')
                            if h == "رقم الشهادة":
                                try:
                                    value = str(int(float(value)))
                                except Exception:
                                    pass
                            elif pd.isna(value) or str(value) == 'nan' or str(value) == '':
                                value = '_____'
                            html_filtered += f'<td>{value}</td>'
                        html_filtered += "</tr>"
                    html_filtered += "</table></body></html>"
                    st.download_button(
                        "⬇️ تحميل التقرير HTML",
                        data=html_filtered,
                        file_name="تقرير_مخصص.html",
                        mime="text/html",
                    )
                    st.session_state.show_export_columns = False
                    st.session_state.selected_columns = []
                    st.rerun()
                else:
                    st.warning("⚠️ يرجى اختيار عمود واحد على الأقل!")

    if st.session_state.show_export_columns:
        st.markdown("---")
        st.markdown("### ✅ اختر الأعمدة المطلوبة:")
        headers_filtered = []
        cols = st.columns(10)
        for i, col in enumerate(filtered_df.columns):
            col_index = i % 10
            with cols[col_index]:
                if st.checkbox(col, key=f"chk_{col}"):
                    headers_filtered.append(col)
        st.session_state.selected_columns = headers_filtered
        if headers_filtered:
            st.info(f"📌 تم اختيار {len(headers_filtered)} عمود")
        else:
            st.warning("⚠️ لم يتم اختيار أي أعمدة بعد")
        st.markdown(f"**Matched :** {len(filtered_df)}")

    if pick and pick.selection["rows"]:
        displayed_row_index = pick.selection["rows"][0]
        selected_index = filtered_df.index[displayed_row_index]
        st.session_state.selected_row = df.loc[selected_index]
        st.session_state.page = "details"
        st.rerun()


def View_data():
    df = st.session_state.df
    col1, col2, col10 = st.columns([1, 4, 1])
    with col1:
        st.markdown("""
        <style>
        div.stButton > button {
            width: 100%; height: 50px; font-size: 20px; font-weight: bold;
            background-color: #0092ca; color: white; border-radius: 10px;
        }
        div.stButton > button:hover { background-color: #5fc9f3; }
        </style>
        """, unsafe_allow_html=True)
        if can_edit(st.session_state.user):
            with st.expander("📤 تحديث من MTS"):
                st.caption("ارفع ملف Excel الخاص بـ MTS لتحديث الشهادات")
                mts_file = st.file_uploader("اختر ملف Excel", type=["xlsx", "xlsm"])
                if mts_file is not None:
                    if st.button("🔄 تنفيذ التحديث", type="primary", key="run_mts_update"):
                        update_from_mts(mts_file, df.copy())
    with col2:
        st.write("")
    with st.expander("Search ..."):
        search_values = show_search_interface(df)
    filtered_df = filter_dataframe(df, search_values)
    with col10:
        st.markdown(f"**📊 Matched : {len(filtered_df)}**")
    show_data_table(df, search_values)


# =========================
# 10) التقارير (من Google Sheets)
# =========================

def report_page():
    st.title("تقارير")
    today = pd.Timestamp.today().normalize()
    df = st.session_state.df
    if df.empty:
        st.info("لا توجد بيانات")
        return

    with st.expander("📄 تقرير الحالات"):
        try:
            excluded = ['مـٌعَلـَق', 'منتهى', 'تحت التسوية', 'جارى تسليم الإفراج']
            status_col = df['الحالة'].astype(str).str.strip()
            dfr = df[~(
                status_col.isin(excluded) |
                (status_col == '') |
                (status_col == 'nan') |
                (status_col.isna())
            )].copy()

            dfr = dfr[~((dfr['إسم الشركة'].astype(str).str.contains('هيات')) &
                         ((dfr['تاريخ إستلام الورق'].isna()) |
                          (dfr['تاريخ إستلام الورق'].astype(str).str.strip() == '') |
                          (dfr['تاريخ إستلام الورق'].astype(str).str.strip() == 'nan')))]

            dfr['تاريخ إستلام الورق'] = dfr['تاريخ إستلام الورق'].fillna('_____')
            yard_empty = (
                dfr['ساحة الكشف'].isna() |
                (dfr['ساحة الكشف'].astype(str).str.strip() == '') |
                (dfr['ساحة الكشف'].astype(str).str.strip() == '_____')
            )
            yard_filled = (
                (~dfr['ساحة الكشف'].isna()) &
                (dfr['ساحة الكشف'].astype(str).str.strip() != '') &
                (dfr['ساحة الكشف'].astype(str).str.strip() != '_____')
            )
            expected_arrival = pd.to_datetime(dfr['التاريخ المتوقع الوصول'], errors='coerce')
            dfr.loc[
                (dfr['الحالة'].str.strip() == 'مدفوع') &
                (
                    yard_empty |
                    (yard_filled & expected_arrival.notna() & (expected_arrival > today))
                ),
                'الحالة'] = 'مدفوع مسبق'

            dfr.loc[(dfr['الحالة'].str.strip() == 'مدفوع') &
                    (~((dfr['ساحة الكشف'].isna()) |
                        (dfr['ساحة الكشف'].astype(str).str.strip() == '') |
                        (dfr['ساحة الكشف'].astype(str).str.strip() == '_____'))),
                    'الحالة'] = 'مدفوع جاهز للصرف'

            def clean_containers(val):
                if pd.isna(val) or str(val).strip() == '' or str(val).strip() == 'nan':
                    return '_____'
                parts = str(val).split(' + ')
                non_zero = [p for p in parts if 'X0' not in p]
                if len(non_zero) == 0:
                    return '_____'
                elif len(non_zero) == 1:
                    return non_zero[0]
                else:
                    return ' + '.join(non_zero)

            if 'عدد الحاويات' in dfr.columns:
                dfr['عدد الحاويات'] = dfr['عدد الحاويات'].apply(clean_containers)

            def clean_datetime(val):
                if pd.isna(val) or str(val).strip() == '' or str(val).strip() == '_____' or str(val).strip() == 'nan':
                    return '_____'
                if ' ' in str(val):
                    return str(val).split(' ')[0]
                if 'T' in str(val):
                    return str(val).split('T')[0]
                return str(val)

            date_cols = ['تاريخ إستلام الورق', 'تاريخ 46', 'تاريخ الكشف', 'التاريخ المتوقع الوصول',
                         'تاريخ الوصول الفعلي', 'تاريخ السماح', 'تاريخ الاعتماد', 'تاريخ السداد']
            for col in date_cols:
                if col in dfr.columns:
                    dfr[col] = dfr[col].apply(clean_datetime)

            dfr = dfr.fillna('_____')

            if 'رقم الشهادة' in dfr.columns:
                dfr['رقم الشهادة'] = dfr['رقم الشهادة'].astype(str).str.replace('.0', '', regex=False)
                dfr['رقم الشهادة'] = dfr['رقم الشهادة'].str.extract(r'(\d+)').fillna('_____')

            required_cols = ['إسم الشركة', 'رقم الشهادة', 'رقم ACID', 'رقم البوليصة', 'الصنف',
                             'العدد', 'عدد الحاويات',
                             'طلب فحص واردات', 'طلب سلامة غذاء', 'دمغة وموازين',
                             'تاريخ 46', 'تاريخ الكشف', 'ساحة الكشف', 'ملاحظات']
            available_cols = [c for c in required_cols if c in dfr.columns]
            df_display = dfr[available_cols].copy()

            html = """
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: Arial; background: #f4f6f7; padding: 30px; }
                .company { text-align: center; font-size: 32px; font-weight: bold; color: darkblue; margin-bottom: 40px; }
                .status { font-size: 22px; font-weight: bold; color: darkred; margin: 30px 0 10px; border-right: 6px solid darkred; padding-right: 10px; }
                table { width: 100%; border-collapse: collapse; background: white; margin-bottom: 25px; }
                th { background: #dff9fb; padding: 8px; border: 1px solid #ccc; word-wrap: break-word; }
                td { padding: 8px; border: 1px solid #ddd; text-align: center; word-wrap: break-word; }
            </style>
            </head>
            <body>
            <div class="company">مؤسسة الفهد للخدمات الملاحية و الجمركية</div>
            """

            if 'الحالة' in dfr.columns:
                for status, group in dfr.groupby('الحالة'):
                    group_display = group[available_cols].copy()
                    html += f'<div class="status">{status}</div><table><tr>'
                    for col in group_display.columns:
                        html += f'<th>{col}</th>'
                    html += '</tr>'
                    for _, row in group_display.iterrows():
                        html += '<tr>'
                        for col in group_display.columns:
                            html += f'<td>{row[col]}</td>'
                        html += '</tr>'
                    html += '</table>'

            html += '</body></html>'
            st.components.v1.html(html, height=900, scrolling=True)
            st.download_button(
                "⬇️ تحميل تقرير الحالات HTML",
                data=html,
                file_name="تقرير_الحالات.html",
                mime="text/html",
            )
        except Exception as e:
            st.error(f"خطأ في تقرير الحالات: {e}")

    with st.expander("تقرير انتظار الوصول"):
        try:
            df_last = df.copy()
            if 'الحالة' in df_last.columns:
                df_last['الحالة'] = df_last['الحالة'].astype(str).str.strip()

            required_cols = ['ساحة الكشف', 'تاريخ إستلام الورق', 'رقم ACID', 'الحالة']
            if all(col in df_last.columns for col in required_cols):
                if "التاريخ المتوقع الوصول" in df_last.columns:
                    df_last["التاريخ المتوقع الوصول"] = pd.to_datetime(
                        df_last["التاريخ المتوقع الوصول"],
                        errors="coerce",
                        dayfirst=True,
                    )
                yard_empty = (
                    df_last['ساحة الكشف'].isna() |
                    (df_last['ساحة الكشف'].astype(str).str.strip() == '') |
                    (df_last['ساحة الكشف'].astype(str).str.strip() == '_____')
                )
                yard_filled = (
                    (df_last['ساحة الكشف'].notna()) &
                    (df_last['ساحة الكشف'].astype(str).str.strip() != '') &
                    (df_last['ساحة الكشف'].astype(str).str.strip() != '_____')
                )
                arrival_future = (
                    yard_filled &
                    df_last["التاريخ المتوقع الوصول"].notna() &
                    (df_last["التاريخ المتوقع الوصول"] > today)
                )
                df_waiting = df_last[
                    (yard_empty | arrival_future) &
                    (df_last['تاريخ إستلام الورق'].notna()) &
                    (df_last["رقم ACID"].notna()) &
                    (~df_last['الحالة'].astype(str).str.strip().isin(['منتهى', 'مُعَلَّق']))
                ].copy()

                df_waiting = df_waiting.fillna('_____')
                if "التاريخ المتوقع الوصول" in df_waiting.columns:
                    df_waiting["التاريخ المتوقع الوصول"] = df_waiting["التاريخ المتوقع الوصول"].replace('_____', 'لم يستدل')
                    df_waiting.loc[(df_waiting['الحالة'].isna()) | (df_waiting['الحالة'].astype(str).str.strip() == '') | (df_waiting['الحالة'].astype(str).str.strip() == 'nan'), 'الحالة'] = 'انتظار وصول'
                    df_waiting["التاريخ المتوقع الوصول_temp"] = pd.to_datetime(df_waiting["التاريخ المتوقع الوصول"].replace('لم يستدل', pd.NaT), errors='coerce', dayfirst=True)
                    df_waiting = df_waiting.sort_values(by="التاريخ المتوقع الوصول_temp", ascending=True, na_position='last')
                    df_waiting = df_waiting.drop(columns=["التاريخ المتوقع الوصول_temp"])

                headers_waiting = ["إسم الشركة", "تاريخ إستلام الورق", "رقم ACID", "رقم الشهادة", "التوكيل",
                                   "رقم البوليصة", "عدد الحاويات", "العدد", "الصنف", "التاريخ المتوقع الوصول"]
                html_waiting = """
                <!DOCTYPE html>
                <html lang="ar" dir="rtl">
                <head><meta charset="UTF-8">
                <title>تقرير انتظار وصول</title>
                <style>
                body { font-family: Arial; background: #f4f6f7; padding: 30px; }
                .company { text-align: center; font-size: 32px; font-weight: bold; color: darkblue; margin-bottom: 40px; }
                table { width: 100%; border-collapse: collapse; background: white; }
                th { background: #dff9fb; padding: 8px; border: 1px solid #ccc; }
                td { padding: 8px; border: 1px solid #ddd; text-align: center; }
                </style></head><body>
                <div class="company">مؤسسة الفهد للخدمات الملاحية و الجمركية</div>
                <h2 style="text-align:center; color:darkred;">تقرير انتظار وصول</h2>
                <table><tr>
                """
                for h in headers_waiting:
                    html_waiting += f"<th>{h}</th>"
                html_waiting += "</tr>"
                for _, r in df_waiting.iterrows():
                    html_waiting += "<tr>"
                    for h in headers_waiting:
                        value = r.get(h, '_____')
                        if h == "رقم الشهادة":
                            try:
                                value = str(int(float(value)))
                            except Exception:
                                pass
                        elif pd.isna(value) or str(value) == 'nan' or str(value) == '':
                            value = '_____'
                        html_waiting += f'<td>{value}</td>'
                    html_waiting += "</tr>"
                html_waiting += "</table></body></html>"
                st.components.v1.html(html_waiting, height=600, scrolling=True)
                st.download_button(
                    "⬇️ تحميل تقرير انتظار الوصول HTML",
                    data=html_waiting,
                    file_name="انتظار_الوصول.html",
                    mime="text/html",
                )
            else:
                st.warning("الأعمدة المطلوبة غير متوفرة في البيانات")
        except Exception as e:
            st.error(f"خطأ في تقرير انتظار الوصول: {e}")


# =========================
# 11) التطبيق الرئيسي
# =========================

def main_app():
    st.markdown("""
        <h1 style='text-align: center; color: white; font-size: 2.5em; font-weight: bold;'>
        مؤسسة الفهــــــــــــد للخدمات الجمركيــــة والملاحيـــــــة
    """, unsafe_allow_html=True)
    set_background(BACK22)

    user = st.session_state.user

    st.sidebar.markdown(f"**المستخدم:** {st.session_state.username}")
    if is_admin(user):
        st.sidebar.markdown("**الصلاحية:** صلاحيات كاملة (كل الشركات)")
    else:
        role_label = "قراءة وتعديل" if can_edit(user) else "قراءة فقط"
        allowed = user_allowed_companies(user)
        if allowed:
            st.sidebar.markdown(f"**الصلاحية:** {role_label} — شركات محددة ({len(allowed)})")
        else:
            st.sidebar.markdown(f"**الصلاحية:** {role_label} — كل الشركات")
    if st.sidebar.button("خروج"):
        st.session_state.authenticated = False
        st.session_state.user = None
        st.session_state.clear()
        st.rerun()

    if st.session_state.page == "details":
        show_certificate_details(st.session_state.selected_row)
        return

    pages = [
        st.Page(View_data, title="Data", url_path="data"),
    ]
    if can_edit(user):
        pages.append(st.Page(lambda: add_new_certificate(st.session_state.df, get_sorted_companies(st.session_state.df), get_sorted_authorizations(st.session_state.df)), title="Add New", url_path="add_new"))
    pages.append(st.Page(report_page, title="Reports", url_path="reports"))

    pg = st.navigation(pages, position="top")
    pg.run()


def main():
    initialize_session_state()

    if not st.session_state.authenticated:
        users = get_users()
        show_login_screen(users)
        st.stop()

    apply_theme()

    try:
        df = load_data()
        df = filter_by_access(df, st.session_state.user)
        st.session_state.df = df
        st.session_state.sorted_companies = get_sorted_companies(df)
        st.session_state.sorted_authorizations = get_sorted_authorizations(df)
        main_app()
    except Exception as e:
        st.error(f"خطأ في تشغيل التطبيق: {e}")
        st.info("تأكد من إعداد secrets: google_sheet_id و gcp_service_account")


if __name__ == "__main__":
    main()
    show_footer()
