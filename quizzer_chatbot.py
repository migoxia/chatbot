import html
import tiktoken
import time
import re
import openai
import base64
import json
import streamlit as st
from streamlit_modal import Modal
from streamlit_lottie import st_lottie


import sqlite3
from db_connection import db
from util import generate_id,generate_time
import requests
from flask import Flask, request
from streamlit_cookies_controller import CookieController, RemoveEmptyElementContainer
import os


def decrypt_uid(encrypted_uid: str, key: str) -> str:
    if encrypted_uid:
        decoded_bytes = base64.urlsafe_b64decode(encrypted_uid.encode())
        decoded_str = decoded_bytes.decode()
        decrypted_chars = [chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(decoded_str)]
        return ''.join(decrypted_chars)

def format_message(msg):
    msg = re.sub(r'<topic>(.*?)</topic>', r'**\1**', msg)
    msg = re.sub(r'<question>(.*?)</question>', r'\n\1', msg)
    return msg
    
controller = CookieController()
RemoveEmptyElementContainer()

cookie_uid = controller.get('secrectID')
cookie_cid = controller.get('course_id')

key = 'mysecretkey'
if cookie_uid:
    uid = decrypt_uid(cookie_uid, key)
    if 'course_id' not in st.session_state:
        st.session_state['course_id'] = cookie_cid

    course_id=st.session_state['course_id']
    staff=['manhlai','abchan','shujunxia2']
    if course_id[0]:
        # cursor.execute("""
        #     SELECT course_department, course_name, course_description, course_prompt
        #     FROM courses
        #     WHERE course_id = ?
        # """, (course_id,))
        # course_data = cursor.fetchone()
        course_data = db.courses.find_one({"course_id": course_id})
        teacher_id = course_data.get('teacher_id', '')
    else:
        st.error("Course ID not found!")
        st.page_link("https://gel-student.cs.cityu.edu.hk/", label="Go Back to Home", icon="🏠")
        st.stop() 

    if 'generate_quiz_button' not in st.session_state:
        st.session_state["generate_quiz_button"]=False
    
    if 'practice_quiz' not in st.session_state:
        st.session_state["practice_quiz"]=False

    if 'generate_quiz_usr' not in st.session_state:
        st.session_state["generate_quiz_usr"]=''
    
    if 'practice_quiz_usr' not in st.session_state:
        st.session_state["practice_quiz_usr"]=''

    if 'topic_not_inserted_quizzer' not in st.session_state:
        st.session_state['topic_not_inserted_quizzer']=True

    if 'topic_id_quizzer' not in st.session_state:
        st.session_state['topic_id_quizzer'] = generate_id()
    
    topic_id=st.session_state['topic_id_quizzer']

    encoding = tiktoken.encoding_for_model("gpt-35-turbo-0613")


    if 'admin' not in st.session_state:
        if uid in staff or uid in teacher_id:
            st.session_state['admin']=True
        else:
            st.session_state['admin']=False

    # Azure API credentials
    azure_key = "c42959fcc37648f0bdee8ed85f0ea6ea"
    azure_endpoint = "https://abchan-fite-gpt.openai.azure.com/"
    azure_version = "2023-07-01-preview"

    client = openai.AzureOpenAI(
        api_key=azure_key,
        api_version=azure_version,
        azure_endpoint=azure_endpoint
    )

    # Database connection
    def create_connection():
        conn = sqlite3.connect('chatbot.db')
        return conn

    def fetch_quizzes(conn,course_id):
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT quiz_name FROM quiz_topic WHERE course_id = ?", (course_id,))
        quizzes = [row[0] for row in cursor.fetchall()]
        return quizzes


    def fetch_topics(conn, quiz_name, course_id):
        cursor = conn.cursor()
        cursor.execute("SELECT topic FROM quiz_topic WHERE quiz_name = ? AND course_id = ?", (quiz_name, course_id))
        topics = [row[0] for row in cursor.fetchall()]
        return topics

    def insert_quiz_topic(conn, quiz, topic,course_id):
        sql_insert = '''INSERT INTO quiz_topic(qt_id,quiz_name, topic, course_id) VALUES(?,?, ?, ?)'''
        cur = conn.cursor()
        cur.execute(sql_insert, (generate_id(),quiz, topic, course_id))
        conn.commit()

    def db_delete_quiz(conn, quiz_name, course_id):
        cursor = conn.cursor()
        cursor.execute("DELETE FROM quiz_topic WHERE quiz_name = ? AND course_id = ?", (quiz_name, course_id))
        conn.commit()

    conn = create_connection()
    cursor = conn.cursor()

    # Page setup

    # Initialize session state for quizzer messages
    if "quizzer_messages" not in st.session_state:
        st.session_state["quizzer_messages"] = [
            {"role": "system", "content": ''
            # '''
            #     You are a quizzer that generates questions about computer science concepts. 
            #     You are friendly and concise. You will be asked to generate  
            #     a question on a particular topic. The student will respond, and you will check the student's response. 
            #     The student can then ask for more explanation, or get the next question. 
            #     You need to keep a list of questions already asked in the session to prevent repeat questions. 
            #     You can also generate incorrect code (e.g., syntax or logical errors) that needs debugging. 
            #     The student then tries to fix the code, and you check the result. 
            #     Mark the beginning and end of a question with <question> and </question>. 
            #     Mark the beginning and end of a topic with <topic> and </topic>.
            #     If the answer is correct, respond with <correct>. If the answer is incorrect, respond with <incorrect>.
            # '''
            },
            {"role": "assistant", "content": "Please choose a quiz for me to generate questions for you."}
        ]

    if "correct_assistant_msg" not in st.session_state:
        st.session_state["correct_assistant_msg"] = []

    if "incorrect_assistant_msg" not in st.session_state:
        st.session_state["incorrect_assistant_msg"] = []

    if "t_list" not in st.session_state:
        st.session_state["t_list"] = []


    if "score" not in st.session_state:
        st.session_state["score"] = 0

    if "num_answered" not in st.session_state:
        st.session_state["num_answered"] = 0

    if "incorrect_questions" not in st.session_state:
        st.session_state["incorrect_questions"] = []

    if "quiz_ended" not in st.session_state:
        st.session_state["quiz_ended"] = False

    if "next_question_enabled" not in st.session_state:
        st.session_state["next_question_enabled"] = False

    # Connect to database and create tables


    custom_css = """
    <style>
    .admin-label {
        color: #FF6347;
        font-weight: bold;
        font-size: 16px;
    }

    </style>
    """

    st.markdown(custom_css, unsafe_allow_html=True)

    busy_icon_css = """
    <style>
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    .busy-icon {
        border: 4px solid #f3f3f3;
        border-top: 4px solid #3498db;
        border-radius: 50%;
        width: 20px;
        height: 20px;
        animation: spin 2s linear infinite;
        display: inline-block;
    }
    </style>
    """

    st.markdown(busy_icon_css, unsafe_allow_html=True)

    # Sidebar - Course selection and system prompt update
    with st.sidebar:
        if uid in staff or uid in teacher_id:
            if st.button("Admin/Student View"):
                st.session_state['admin']=not st.session_state['admin']
        st.markdown(
            """
            <style>
            .modal-content {
                margin-top: 2%;  
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        
        if course_data:
            cursor.execute('''
                SELECT * FROM system_prompt
                WHERE course_id = ? AND chatbot_type = ?
                ORDER BY create_time DESC
                LIMIT 1;
            ''', (course_id, 'quizzer'))
            latest_record = cursor.fetchone()

            if latest_record and st.session_state["quizzer_messages"][0]["content"]=='':
                st.session_state["quizzer_messages"][0]["content"] = latest_record[0]
            else:
                course_department = course_data.get('course_department', '')
                course_name = course_data.get('course_name', '')
                course_description = course_data.get('course_description', '')
                course_prompt = course_data.get('course_prompt', '')
                # Format the course_prompt with the retrieved data
                formatted_prompt = f'''
                    You are a quizzer that generates questions about the {course_department} course {course_name}. 
                    Course Description: {course_description}
                    You are friendly and concise. You will be asked to generate  
                    a question on a particular topic. 
                    You need to ask a concrete question that has an explicit answer. For example, instead of asking "What is Bayesian estimation?", you should ask a certain application problem of Bayesian estimation or a calculation problem, so that the student can give an explicit answer instead of abstract concepts. 
                    The student will respond, and you will check the student's response. 
                    The student can then ask for more explanation, or get the next question. 
                    You need to keep a list of questions already asked in the session to prevent repeating questions. 
                    You can also generate incorrect code (e.g., syntax or logical errors) that needs debugging. 
                    The student then tries to fix the code, and you check the result. 
                    Mark the beginning and end of a question with <question> and </question>. 
                    Mark the beginning and end of a topic with <topic> and </topic>. For example, if the topic is Java Syntax, output <topic>Java Syntax</topic>.
                    Generate only one question for one topic at one time.
                    If the answer is correct, respond with <correct>. If the answer is incorrect, respond with <incorrect>.
                    If you can't give <correct> or <incorrect> because the user doesn't know the answer or directly asks for explanation, end your response with "Do you want further explanation or next question?"
                '''
                if st.session_state["quizzer_messages"][0]["content"]=='':
                    st.session_state["quizzer_messages"][0]["content"] = formatted_prompt
            st.write(f"Course ID: {course_id}")
            # st.sidebar.success("Course prompt updated successfully!")


        # teacher_id = course_data.get('teacher_id', '')
        # if uid in staff or uid in teacher_id:
        if st.session_state['admin']:
            st.markdown('<label class="admin-label">Enter new System Prompt</label>', unsafe_allow_html=True)
            @st.dialog("Update System Prompt")
            def update_system_prompt():
                new_system_prompt = st.text_area("New Prompt:", st.session_state["quizzer_messages"][0]["content"], height=200)
                submitted_curr= st.button("Save for this session")
                if submitted_curr:
                    st.session_state["quizzer_messages"][0]["content"] = new_system_prompt
                    st.success("System prompt updated successfully!")
                    st.rerun()

                submitted_db= st.button("Save for all sessions")
                if submitted_db:
                    st.session_state["quizzer_messages"][0]["content"] = new_system_prompt
                    conn = create_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO system_prompt (prompt,course_id, uid, chatbot_type)
                        VALUES (?, ?, ?, ?)
                    ''', (new_system_prompt,course_id, uid, 'quizzer'))
                    conn.commit()
                    st.success("System prompt updated successfully!")
                    st.rerun()
            if st.button("Update System Prompt"):
                update_system_prompt()


        if st.session_state['admin']:
            with st.form("customize_quiz"):
                st.markdown('<label class="admin-label">Customize Quiz</label>', unsafe_allow_html=True)
                quiz_name_input = st.text_input("Enter Quiz Name:")
                quiz_topic_input = st.text_input("Enter Topic:")
                add_topic=st.form_submit_button("Add Topic")
                if add_topic:
                    if quiz_topic_input and quiz_topic_input not in st.session_state["t_list"]:
                        st.session_state["t_list"].append(quiz_topic_input)
                        st.sidebar.success(f"Topic {quiz_topic_input} added successfully!")
                st.write("Topics added: ", st.session_state["t_list"])

                add_quiz = st.form_submit_button("Add Quiz")
                if add_quiz:
                    if quiz_name_input and quiz_topic_input:
                        for topic in st.session_state["t_list"]:
                            insert_quiz_topic(conn, quiz_name_input, topic, course_id)
                        st.sidebar.success(f"Quiz {quiz_name_input} added successfully!")
                        st.session_state["t_list"]=[]
                        
                    elif not quiz_topic_input:
                        st.sidebar.warning("Please enter a quiz topic.")
                    elif not quiz_name_input:
                        st.sidebar.warning("Please enter a quiz name.")
                
                quizzes=fetch_quizzes(conn,course_id)
                if quizzes:
                    select_quiz = st.selectbox(
                        "Select Quiz",
                        quizzes,
                        key="select_quiz_key"
                    )

                    topics = fetch_topics(conn, select_quiz, course_id)
                    st.write(f"Topics in {select_quiz}: {topics}")
                    delete_quiz = st.form_submit_button("Delete Quiz")
                    practice_quiz = st.form_submit_button("Practice Quiz",help="You need to End Quiz before generating a new quiz.")
                    if delete_quiz:
                        db_delete_quiz(conn, select_quiz, course_id)
                        st.success(f"Quiz '{select_quiz}' has been deleted.")
                        quizzes = fetch_quizzes(conn, course_id)
                        st.rerun()
                    if practice_quiz:
                        topic_message = f"Generate a quiz question randomly from one of the following topics: {topics}"
                        st.session_state["quizzer_messages"].append({"role": "user", "content": topic_message})
                        if st.session_state['topic_not_inserted_quizzer']:
                            db.topics.insert_one(
                                {
                                    "topic_id": st.session_state['topic_id_quizzer'],
                                    "user_id": uid,
                                    "course_id": course_id,
                                    "latest_gpt_ver": 'gpt-35-turbo-0613',
                                    "chat_title": 'general',
                                    "chatbot_type": "quizzer"
                                }
                            )
                            st.session_state['topic_not_inserted_quizzer']=False
                        total_token_count = sum(len(encoding.encode(message["content"])) for message in st.session_state["quizzer_messages"])
                        user_record = db.users.find_one({"user_id": uid})
                        if user_record:
                            tokens_used = user_record.get("tokens_used")  
                            tokens_available = user_record.get("tokens_available") 
                            tokens_left=tokens_available-tokens_used
                        else:
                            st.write(f"No user record found with user_id: {uid}")
                        if total_token_count>tokens_left:
                            st.error("Quota for this course has been exceeded.")
                        else:
                            result = db.users.update_one(
                                {'user_id': uid}, 
                                {'$inc': {'tokens_used': total_token_count}}  
                            )
                            if result.matched_count == 0:
                                st.write("No token record found with that user_id.")
                            st.sidebar.success(f"Quiz updated: {select_quiz}")
                            st.session_state["practice_quiz_usr"]=topic_message
                            st.session_state["practice_quiz"]=st.session_state["quizzer_messages"]
                else:
                    st.warning("No quizzes available for this course.")   
                    
        with st.form("generate_quiz"):
            quizzes=fetch_quizzes(conn,course_id)
            select_quiz = st.selectbox(
                "Select Quiz",
                quizzes
            )
            topics=fetch_topics(conn, select_quiz, course_id)
            st.write(f"Topics in {select_quiz}: {topics}")
            
            generate_quiz = st.form_submit_button("Generate Quiz",help="You need to End Quiz before generating a new quiz.")
            if select_quiz:
                if generate_quiz:
                
                    topic_message = f"Generate a quiz question randomly from one of the following topics: {topics}"
                    st.session_state["quizzer_messages"].append({"role": "user", "content": topic_message})
                    if st.session_state['topic_not_inserted_quizzer']:
                        db.topics.insert_one(
                            {
                                "topic_id": st.session_state['topic_id_quizzer'],
                                "user_id": uid,
                                "course_id": course_id,
                                "latest_gpt_ver": 'gpt-35-turbo-0613',
                                "chat_title": 'general',
                                "chatbot_type": "quizzer"
                            }
                        )
                        st.session_state['topic_not_inserted_quizzer']=False
                    total_token_count = sum(len(encoding.encode(message["content"])) for message in st.session_state["quizzer_messages"])
                    user_record = db.users.find_one({"user_id": uid})
                    if user_record:
                        tokens_used = user_record.get("tokens_used")  
                        tokens_available = user_record.get("tokens_available") 
                        tokens_left=tokens_available-tokens_used
                    else:
                        st.write(f"No user record found with user_id: {uid}")
                    if total_token_count>tokens_left:
                        st.error("Quota for this course has been exceeded.")
                    else:
                        result = db.users.update_one(
                            {'user_id': uid}, 
                            {'$inc': {'tokens_used': total_token_count}}  
                        )
                        if result.matched_count == 0:
                            st.write("No token record found with that user_id.")
                        # st.chat_message("user").write(topic_message)
                        st.sidebar.success(f"Quiz updated: {select_quiz}")
                        # placeholder = st.empty()
                        # placeholder.markdown('<div class="busy-icon"></div>', unsafe_allow_html=True)
                        st.session_state["generate_quiz_usr"]=topic_message
                        st.session_state["generate_quiz_button"]=st.session_state["quizzer_messages"]
                        

        if st.button("End Quiz",help='show your score and incorrect questions'):
            st.session_state["quiz_ended"] = True

        
    for msg in st.session_state["quizzer_messages"]:
        if msg["role"] == "assistant":
            msg["content"] = format_message(msg["content"])
            if '<correct>' in msg["content"]:
                st.chat_message("assistant").write('✅'+msg["content"].replace('<correct>', '').replace('</correct>', ''))
            elif '<incorrect>' in msg["content"]:
                st.chat_message("assistant").write('❌'+msg["content"].replace('<incorrect>', '').replace('</incorrect>', ''))
            else:
                st.chat_message("assistant").write(msg["content"])
        elif msg["role"] == "user":
            st.chat_message("user").write(msg["content"])

    if st.session_state["practice_quiz"]:
        topic=st.session_state['practice_quiz']
        placeholder = st.empty()
        placeholder.markdown('<div class="busy-icon"></div>', unsafe_allow_html=True)

        response = client.chat.completions.create(
            model="gpt-35-turbo-0613", 
            messages=st.session_state["quizzer_messages"],
        )  
        assistant_msg = response.choices[0].message.content

        formatted_msg = format_message(assistant_msg)
        placeholder.chat_message("assistant").write(formatted_msg)

        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        tokens = encoding.encode(assistant_msg)
        completion_tokens = len(tokens)
        st.session_state["quizzer_messages"].append({"role": "assistant", "content": assistant_msg})
        db.chats.insert_one(
            {
                "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])-1).zfill(2),
                "topic_id": topic_id,
                "time": generate_time(),
                "content": st.session_state["practice_quiz_usr"],
                "role": "user",
                "no_of_tokens": 0,
                # "chatbot_type": "quizzer"
            }
        )
        db.chats.insert_one(
            {
                "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])).zfill(2),
                "topic_id": topic_id,
                "time": generate_time(),
                "content": assistant_msg,
                "role": "assistant",
                "no_of_tokens": total_token_count+completion_tokens,
                # "chatbot_type": "quizzer"
            }
        )
        db.users.update_one(
            {'user_id': uid}, 
            {'$inc': {'tokens_used': total_token_count+ completion_tokens}}  
        )
        st.session_state["practice_quiz"]=False
        st.session_state["practice_quiz_usr"]=''
    
    if st.session_state["generate_quiz_button"]:
        topic=st.session_state['generate_quiz_button']
        placeholder = st.empty()
        placeholder.markdown('<div class="busy-icon"></div>', unsafe_allow_html=True)

        response = client.chat.completions.create(
            model="gpt-35-turbo-0613", 
            messages=st.session_state["quizzer_messages"],
        )  
        assistant_msg = response.choices[0].message.content

        formatted_msg = format_message(assistant_msg)
        placeholder.chat_message("assistant").write(formatted_msg)
        
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        tokens = encoding.encode(assistant_msg)
        completion_tokens = len(tokens)
        st.session_state["quizzer_messages"].append({"role": "assistant", "content": assistant_msg})
        db.chats.insert_one(
            {
                "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])-1).zfill(2),
                "topic_id": topic_id,
                "time": generate_time(),
                "content": st.session_state["generate_quiz_usr"],
                "role": "user",
                "no_of_tokens": 0,
                # "chatbot_type": "quizzer"
            }
        )
        db.chats.insert_one(
            {
                "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])).zfill(2),
                "topic_id": topic_id,
                "time": generate_time(),
                "content": assistant_msg,
                "role": "assistant",
                "no_of_tokens": total_token_count+completion_tokens,
                # "chatbot_type": "quizzer"
            }
        )
        db.users.update_one(
            {'user_id': uid}, 
            {'$inc': {'tokens_used': total_token_count+ completion_tokens}}  
        )
        st.session_state["generate_quiz_button"]=False
        st.session_state["generate_quiz_usr"]=''


    prompt = st.chat_input()
    if prompt:
        st.session_state["quizzer_messages"].append({"role": "user", "content": prompt})
        if st.session_state['topic_not_inserted_quizzer']:
            db.topics.insert_one(
                {
                    "topic_id": st.session_state['topic_id_quizzer'],
                    "user_id": uid,
                    "course_id": course_id,
                    "latest_gpt_ver": 'gpt-35-turbo-0613',
                    "chat_title": 'general',
                    "chatbot_type": "quizzer"
                }
            )
            st.session_state['topic_not_inserted_quizzer']=False
        st.chat_message("user").write(prompt)
        total_token_count = sum(len(encoding.encode(message["content"])) for message in st.session_state["quizzer_messages"])
        user_record = db.users.find_one({"user_id": uid})
        if user_record:
            tokens_used = user_record.get("tokens_used")  
            tokens_available = user_record.get("tokens_available") 
            tokens_left=tokens_available-tokens_used
        else:
            st.write(f"No user record found with user_id: {uid}")
        if total_token_count>tokens_left:
            st.error("Quota for this course has been exceeded.")
        else:
            result = db.users.update_one(
                {'user_id': uid}, 
                {'$inc': {'tokens_used': total_token_count}}  
            )
            if result.matched_count == 0:
                st.write("No token record found with that user_id.")
            placeholder = st.empty()
            placeholder.markdown('<div class="busy-icon"></div>', unsafe_allow_html=True)


            # Fetch AI response
            
            response = client.chat.completions.create(
                model="gpt-35-turbo-0613", 
                messages=st.session_state["quizzer_messages"],
                stream=True  
            )
            messages = []
            for chunk in response:  # Iterate over the stream
                if len(chunk.choices) > 0:
                    # st.write("chunk.choices[0].delta.content",chunk.choices[0].delta.content)
                    if chunk.choices[0].delta.content:
                        messages.append(chunk.choices[0].delta.content)
                        # placeholder.chat_message("assistant").write(''.join(messages))
            assistant_msg = ''.join(messages)
            encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            tokens = encoding.encode(assistant_msg)
            completion_tokens = len(tokens)
            
            if "<question>" in assistant_msg:
                st.session_state["next_question_enabled"] = False

            if "next question" in assistant_msg:
                st.session_state["next_question_enabled"] = True

            if "new question" in assistant_msg:
                st.session_state["next_question_enabled"] = True

            if "another question" in assistant_msg:
                st.session_state["next_question_enabled"] = True

            st.session_state["quizzer_messages"].append({"role": "assistant", "content": assistant_msg})
            db.chats.insert_one(
                {
                    "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])-1).zfill(2),
                    "topic_id": topic_id,
                    "time": generate_time(),
                    "content": prompt,
                    "role": "user",
                    "no_of_tokens": 0,
                    # "chatbot_type": "quizzer"
                }
            )
            db.chats.insert_one(
                {
                    "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])).zfill(2),
                    "topic_id": topic_id,
                    "time": generate_time(),
                    "content": assistant_msg,
                    "role": "assistant",
                    "no_of_tokens": total_token_count+completion_tokens,
                    # "chatbot_type": "quizzer"
                }
            )
            db.users.update_one(
                {'user_id': uid}, 
                {'$inc': {'tokens_used': total_token_count+ completion_tokens}}  
            )
            if "<correct>" in assistant_msg:
                st.session_state["correct_assistant_msg"].append(assistant_msg)
                modified_msg = assistant_msg.replace("<correct>", "").replace("</correct>", "")
                modified_msg="✅"+modified_msg
                animation_url='https://lottie.host/56bf94af-b096-488a-81d2-0b668c838814/mr65K6DyxB.json'
                st_lottie(animation_url, height=200, key="user")

                placeholder.chat_message("assistant").write(modified_msg)
                
                st.session_state["score"] += 1
                st.session_state["num_answered"] += 1
                st.session_state["next_question_enabled"] = True 
            elif "<incorrect>" in assistant_msg:
                st.session_state["incorrect_assistant_msg"].append(assistant_msg)
                modified_msg = assistant_msg.replace("<incorrect>", "").replace("</incorrect>", "")
                modified_msg="❌"+modified_msg
                animation_url='https://lottie.host/dd94aa73-21db-4dc0-9471-909acbff4b85/1sNeV7BjU3.json'
                st_lottie(animation_url, height=150,key="user")
                placeholder.chat_message("assistant").write(modified_msg)
                
                st.session_state["num_answered"] += 1
                for msg in reversed(st.session_state["quizzer_messages"]):
                    if msg["role"] == "assistant" and "<question>" in msg["content"] and "</question>" in msg["content"]:
                        question_start = msg["content"].find("<question>") + len("<question>")
                        question_end = msg["content"].find("</question>")
                        if question_start != -1 and question_end != -1 and question_start < question_end:
                            question = msg["content"][question_start:question_end].strip()
                            st.session_state["incorrect_questions"].append(question)
                        break
                st.session_state["next_question_enabled"] = True 
            else:
                placeholder.chat_message("assistant").write(assistant_msg)

                
    if button_clicked:= st.button("Next Question", disabled=not st.session_state["next_question_enabled"]):
        user_input = "Next question"
        st.session_state["quizzer_messages"].append({"role": "user", "content": user_input})
        total_token_count = sum(len(encoding.encode(message["content"])) for message in st.session_state["quizzer_messages"])
        user_record = db.users.find_one({"user_id": uid})
        if user_record:
            tokens_used = user_record.get("tokens_used")  
            tokens_available = user_record.get("tokens_available") 
            tokens_left=tokens_available-tokens_used
        else:
            st.write(f"No user record found with user_id: {uid}")
        if total_token_count>tokens_left:
            st.error("Quota for this course has been exceeded.")
        else:
            result = db.users.update_one(
                {'user_id': uid}, 
                {'$inc': {'tokens_used': total_token_count}}  
            )
            if result.matched_count == 0:
                st.write("No token record found with that user_id.")
            st.session_state["next_question_enabled"] = False
            placeholder = st.empty()
            placeholder.markdown('<div class="busy-icon"></div>', unsafe_allow_html=True)

            response = client.chat.completions.create(
                model="gpt-35-turbo-0613", 
                messages=st.session_state["quizzer_messages"],
            )  
            assistant_msg = response.choices[0].message.content

            formatted_msg = format_message(assistant_msg)
            placeholder.chat_message("assistant").write(formatted_msg)

            encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            tokens = encoding.encode(assistant_msg)
            completion_tokens = len(tokens)

            st.session_state["quizzer_messages"].append({"role": "assistant", "content": assistant_msg})
            db.chats.insert_one(
                {
                    "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])-1).zfill(2),
                    "topic_id": topic_id,
                    "time": generate_time(),
                    "content": user_input,
                    "role": "user",
                    "no_of_tokens": 0,
                    # "chatbot_type": "quizzer"
                }
            )
            db.chats.insert_one(
                {
                    "chat_id": generate_id() + str(len(st.session_state["quizzer_messages"])).zfill(2),
                    "topic_id": topic_id,
                    "time": generate_time(),
                    "content": assistant_msg,
                    "role": "assistant",
                    "no_of_tokens": total_token_count+completion_tokens,
                    # "chatbot_type": "quizzer"
                }
            )
            db.users.update_one(
                {'user_id': uid}, 
                {'$inc': {'tokens_used': total_token_count+ completion_tokens}}  
            )

            st.rerun()


    if st.session_state["quiz_ended"]:
        st.sidebar.write("Session Summary")
        st.sidebar.write(f"Total Score: {st.session_state['score']}")
        st.sidebar.write(f"Number of Answered Questions: {st.session_state['num_answered']}")
        st.sidebar.write("Incorrect Questions:")
        for idx, question in enumerate(st.session_state["incorrect_questions"], start=1):
            st.sidebar.write(f"{idx}. {question}")

        st.session_state["score"] = 0
        st.session_state["num_answered"] = 0
        st.session_state["incorrect_questions"] = []
        cursor.execute('''
            SELECT * FROM system_prompt
            WHERE course_id = ? AND chatbot_type = ?
            ORDER BY create_time DESC
            LIMIT 1;
        ''', (course_id, 'quizzer'))
        latest_record = cursor.fetchone()

        if latest_record:

            st.session_state["quizzer_messages"] = [
                {"role": "system", "content":latest_record[0]
                },
            #     {"role": "assistant", "content": "Please choose a quiz for me to generate questions for you."}
            ]
        st.session_state["quiz_ended"] = False

    st.caption("Use Shift+Enter to add a new line.")
    st.sidebar.write("Disclaimer: This chatbot is provided for educational purposes only. Logs of your chat sessions will be saved and reviewed by the teaching team to improve the course content and chatbot experience.")
    st.sidebar.write("Support: If you encounter any issues or have any feedback, please reach out to the team via email at: gel.support@cityu.edu.hk.")


    # Close the database connection when the script ends
    conn.close()
