import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os

st.set_page_config(page_title="Finance App", layout="wide")  # page config

category_file = "categories.json"

if "categories" not in st.session_state:
    st.session_state.categories = {
        "Uncategorised": []
    }
    
if os.path.exists(category_file):
    with open(category_file,"r") as f:
        st.session_state.categories = json.load(f)
        
def save_categories():
    with open(category_file,"w") as f:
        json.dump(st.session_state.categories, f)

def categorise_transactions(df):
    df["Category"] = "Uncategorised"
    
    for category, keywords in st.session_state.categories.items():
        if category == "Uncategorised" or not keywords:
            continue
        
        lowered_keywords = [keyword.lower().strip() for keyword in keywords]
        
        for idx, row in df.iterrows():
            description = row["Description"].lower().strip()
            if description in lowered_keywords:
                df.at[idx, "Category"] = category

    return df

def load_transactions(file):
    try:
        df = pd.read_csv(file, skiprows=4)
        df.columns = [col.strip() for col in df.columns]
        df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")  # convert date to date/time format
        
        #----- Clean the "Paid out" column to remove currency symbols
        if "Paid out" in df.columns:
            # Remove currency symbols/commas and convert to numbers, forcing errors to NaN (which becomes 0)
            df["Paid out"] = df["Paid out"].astype(str).str.replace(r'[^\d.]', '', regex=True)
            df["Paid out"] = pd.to_numeric(df["Paid out"], errors='coerce').fillna(0.0)
        
        return categorise_transactions(df=df)
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None

def add_keyword_to_category(category, keyword):
    keyword = keyword.strip()
    if keyword and keyword not in st.session_state.categories[category]:
        st.session_state.categories[category].append(keyword)
        save_categories()
        return True

    return False

def main():
    st.title("Simple Finance Dashboard")
    
    # Initialize df in session state so it doesn't break if page reruns without upload
    if "df" not in st.session_state:
        st.session_state.df = None
    
    #----- Upload file -----
    uploaded_file = st.file_uploader("Upload your transaction csv file", type=["csv"])
    
    if uploaded_file is not None and st.session_state.df is None:
        df = load_transactions(uploaded_file)
        if df is not None:
            st.session_state.df = df.copy()
            
    if st.session_state.df is not None:
        st.write(st.session_state.df)
        
        [tab1] = st.tabs(["TEST CHECK"])
        with tab1:
            new_category = st.text_input("New Category Name")
            add_button = st.button("Add Category")
            if add_button and new_category:
                if new_category not in st.session_state.categories:
                    st.session_state.categories[new_category] = []
                    save_categories()
                    st.rerun()
                    
            st.subheader("Your Expenses")
            
            # We don't hide the index anymore so pandas can keep track of row IDs accurately
            edited_df = st.data_editor(
                st.session_state.df[["Date", "Description", "Paid out", "Category"]],
                column_config = {
                    "Date": st.column_config.DateColumn(label="Date", format="DD/MM/YYYY"),
                    "Category": st.column_config.SelectboxColumn(
                        "Category",
                        options=list(st.session_state.categories.keys())
                    )
                    },
                use_container_width=True,
                key="category_editor"
            )
            
            save_button = st.button("Apply changes", type="primary")
            if save_button:
                # Use Streamlit's built-in change tracking dictionary
                edited_rows = st.session_state.category_editor.get("edited_rows", {})
                
                for idx_str, changes in edited_rows.items():
                    if "Category" in changes:
                        idx = int(idx_str)  # Streamlit dictionary keys are strings
                        new_cat = changes["Category"]
                        
                        # Correctly pull the description string from the specific row
                        description = st.session_state.df.at[idx, "Description"]
                        
                        # Update the underlying dataframe safely
                        st.session_state.df.at[idx, "Category"] = new_cat
                        
                        # Add keyword rule to categories
                        add_keyword_to_category(new_cat, description)
                
                st.success("Changes saved successfully!")
                st.rerun()

            st.subheader("Expense Summary")
            category_totals = st.session_state.df.groupby("Category")["Paid out"].sum().reset_index()
            category_totals = category_totals.sort_values("Paid out", ascending=False)
            
            st.dataframe(
                category_totals,
                column_config={
                    "Paid out": st.column_config.NumberColumn("Paid out", format="£%.2f")
                },
                hide_index=True
            )
            
            fig = px.pie(
                category_totals,
                values="Paid out",
                names="Category",
                title="Expenses by Category"
            )
            st.plotly_chart(fig, use_container_width=True)

main()
