import io

import pandas as pd
import plotly.express as px
import streamlit as st

import storage
from categoriser import CONFIDENCE_THRESHOLD, categorise_transactions, jev_available

st.set_page_config(page_title="Finance App", layout="wide")  # page config

if "categories" not in st.session_state:
    st.session_state.categories = storage.load_categories()

if "overrides" not in st.session_state:
    st.session_state.overrides = storage.load_overrides()

if "df" not in st.session_state:
    st.session_state.df = storage.load_saved_transactions()


def read_statement(file):
    """Read the bank CSV, coping with non-UTF-8 files (e.g. the pound sign in Windows-1252)."""
    raw = file.getvalue()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")

    # Statements start with a few lines of account info; find the real header row.
    lines = text.splitlines()
    def is_header(line):
        cells = [c.strip().strip('"').strip("'").lower() for c in line.lstrip("﻿").split(",")]
        return "date" in cells and "description" in cells

    header_idx = next((i for i, line in enumerate(lines) if is_header(line)), None)
    if header_idx is None:
        preview = "\n".join(lines[:8])
        raise ValueError(f"Couldn't find a header row with Date and Description columns. First lines of the file were:\n{preview}")
    return pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))


def load_transactions(file):
    try:
        df = read_statement(file)
        df.columns = [col.strip() for col in df.columns]
        df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")  # convert date to date/time format

        #----- Clean the "Paid out" column to remove currency symbols
        df["Paid out"] = df["Paid out"].astype(str).str.replace(r'[^\d.]', '', regex=True)
        df["Paid out"] = pd.to_numeric(df["Paid out"], errors='coerce').fillna(0.0)

        return df[["Date", "Description", "Paid out"]]
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
    return None


def add_new_transactions(new_df):
    """Categorise only the rows we haven't saved before, then persist everything."""
    new_df = storage.new_rows_only(new_df, st.session_state.df)
    if new_df.empty:
        st.info("No new transactions found in that file.")
        return

    with st.spinner("Jev is categorising your transactions..."):
        new_df = categorise_transactions(new_df, st.session_state.categories, st.session_state.overrides)

    combined = pd.concat([st.session_state.df, new_df], ignore_index=True) if st.session_state.df is not None else new_df
    st.session_state.df = combined.reset_index(drop=True)
    storage.save_transactions(st.session_state.df)
    st.success(f"Added {len(new_df)} new transactions.")


def show_summary(category_totals):
    st.subheader("Expense Summary")
    st.dataframe(
        category_totals,
        column_config={"Paid out": st.column_config.NumberColumn("Paid out", format="£%.2f")},
        hide_index=True,
    )
    fig = px.pie(category_totals, values="Paid out", names="Category", title="Expenses by Category")
    st.plotly_chart(fig, use_container_width=True)


def show_snapshot(name):
    snapshot = storage.load_snapshot(name)
    st.header(f"Snapshot: {name}")
    st.caption(f"Saved {snapshot['saved_at'].replace('T', ' ')} - this is a read-only copy.")
    st.subheader("Your Expenses")
    st.dataframe(
        snapshot["table"],
        column_config={
            "Date": st.column_config.DateColumn(label="Date", format="DD/MM/YYYY"),
            "Confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
        },
        use_container_width=True,
    )
    show_summary(snapshot["summary"])


def sidebar():
    """Save the current view and browse saved snapshots (stored in the app's 'snapshots' folder)."""
    st.sidebar.header("Saved snapshots")
    if st.session_state.df is not None:
        name = st.sidebar.text_input("Snapshot name", key="snapshot_name").strip()
        if st.sidebar.button("Save current table & summary", disabled=not name):
            storage.save_snapshot(name, st.session_state.df)
            st.session_state.viewing = name
            st.rerun()

    names = storage.list_snapshots()
    if st.session_state.get("viewing") not in names:
        st.session_state.viewing = None
    if not names:
        st.sidebar.caption("No snapshots yet.")
        return
    if st.session_state.viewing and st.sidebar.button("← Back to live data"):
        st.session_state.viewing = None
        st.rerun()
    for n in names:
        row = st.sidebar.columns([5, 1])
        if row[0].button(n, key=f"open_{n}", use_container_width=True,
                         type="primary" if n == st.session_state.viewing else "secondary"):
            st.session_state.viewing = n
            st.rerun()
        if row[1].button("🗑", key=f"del_{n}", help=f"Delete '{n}'"):
            storage.delete_snapshot(n)
            st.rerun()


def main():
    st.title("Simple Finance Dashboard")
    sidebar()
    if st.session_state.get("viewing"):
        show_snapshot(st.session_state.viewing)
        return

    if not jev_available():
        st.warning("TYPESAFE_API_KEY is not set - Jev is disabled, new transactions will stay Uncategorised.")

    #----- Upload file -----
    uploaded_file = st.file_uploader("Upload your transaction csv file", type=["csv"])

    if uploaded_file is not None and st.session_state.get("last_upload") != uploaded_file.file_id:
        st.session_state.last_upload = uploaded_file.file_id
        new_df = load_transactions(uploaded_file)
        if new_df is not None:
            add_new_transactions(new_df)

    if st.session_state.df is not None:
        [tab1] = st.tabs(["TEST CHECK"])
        with tab1:
            new_category = st.text_input("New Category Name")
            new_description = st.text_input("What belongs in this category? (helps Jev)")
            add_button = st.button("Add Category")
            if add_button and new_category:
                if new_category not in st.session_state.categories:
                    st.session_state.categories[new_category] = new_description
                    storage.save_categories(st.session_state.categories)
                    st.rerun()

            col1, col2 = st.columns(2)
            recategorise = col1.button(
                "Re-categorise 'Uncategorised' with Jev",
                disabled=not jev_available(),
                help="Runs Jev again on transactions that are still Uncategorised (e.g. after adding categories).",
            )
            if recategorise:
                df = st.session_state.df
                todo = df[df["Source"].isin(["none", "jev"])]
                with st.spinner("Jev is categorising your transactions..."):
                    updated = categorise_transactions(
                        todo[["Date", "Description", "Paid out"]], st.session_state.categories, st.session_state.overrides
                    )
                for column in ["Category", "Source", "Confidence"]:
                    df.loc[updated.index, column] = updated[column]
                storage.save_transactions(df)
                st.rerun()

            st.subheader("Your Expenses")
            st.caption(
                f"Source shows who categorised each row: jev (confidence ≥ {CONFIDENCE_THRESHOLD}), "
                "manual (your correction) or none. Change a category and click Apply to save it and teach the app."
            )

            edited_df = st.data_editor(
                st.session_state.df[["Date", "Description", "Paid out", "Category", "Source", "Confidence"]],
                column_config={
                    "Date": st.column_config.DateColumn(label="Date", format="DD/MM/YYYY"),
                    "Category": st.column_config.SelectboxColumn(
                        "Category",
                        options=list(st.session_state.categories.keys())
                    ),
                    "Confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                },
                disabled=["Date", "Description", "Paid out", "Source", "Confidence"],
                use_container_width=True,
                key="category_editor"
            )

            save_button = st.button("Apply changes", type="primary")
            if save_button:
                edited_rows = st.session_state.category_editor.get("edited_rows", {})

                for idx_str, changes in edited_rows.items():
                    if "Category" in changes:
                        idx = int(idx_str)  # Streamlit dictionary keys are strings
                        new_cat = changes["Category"]
                        description = st.session_state.df.at[idx, "Description"]

                        st.session_state.df.at[idx, "Category"] = new_cat
                        st.session_state.df.at[idx, "Source"] = "manual"

                        # Remember the correction so future uploads of this description match
                        st.session_state.overrides[description] = new_cat
                        storage.save_overrides(st.session_state.overrides)

                storage.save_transactions(st.session_state.df)
                st.success("Changes saved successfully!")
                st.rerun()

            category_totals = st.session_state.df.groupby("Category")["Paid out"].sum().reset_index()
            show_summary(category_totals.sort_values("Paid out", ascending=False))


main()
