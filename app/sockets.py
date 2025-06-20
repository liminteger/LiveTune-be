from flask_socketio import join_room, leave_room
from flask import request
from . import rooms, users
from app.utils import find_room
import random
from app.logger_config import get_logger

logger = get_logger(__name__)
sid_map = {}
uid_map = {}

# ===== HELPER FUNCTIONS =====

def _handle_user_departure(socketio, room_id, uid):
    """Helper function to manage room state when a user departs."""
    room = find_room(rooms, room_id)
    if not room:
        logger.warning(f"Room {room_id} not found during user {uid} departure.")
        return

    if uid in room.current_users:
        room.remove_user(uid)
        logger.info(f"User {uid} removed from room {room_id}.")
        socketio.emit("user_left", {"uid": uid}, room=room_id)

        if not room.current_users: # Room became empty
            if room_id in rooms: del rooms[room_id]
            logger.info(f"Room {room_id} deleted as it became empty.")
        elif room.host == uid: # Room not empty, and departing user was host
            _assign_new_host(socketio, room)

def _assign_new_host(socketio, room):
    """Helper function to assign a new host if current users exist."""
    if room.current_users:
        new_host_uid = random.choice(room.current_users)
        room.host = new_host_uid
        new_host_user = users.get(new_host_uid)
        new_host_username = new_host_user.username if new_host_user else "Unknown user"
        logger.info(f"User {new_host_username} (uid: {new_host_uid}) is now the host of room {room.id}.")
        socketio.emit("host_changed", {"new_host_uid": new_host_uid}, room=room.id)
    else: # Should ideally not be reached if called after checking room.current_users
        if room.id in rooms: del rooms[room.id]
        logger.info(f"Room {room.id} deleted as it became empty during host reassignment.")

# ===== SOCKETS =====

def register_socket_events(socketio):
    @socketio.on("connect")
    def on_connect():
        logger.info(f"Client connected: sid={request.sid}")

    @socketio.on("disconnect")
    def on_disconnect():
        logger.info(f"Client disconnected: {request.sid}")
        uid = uid_map.pop(request.sid, None)

        if uid:
            sid = sid_map.pop(uid, None)
            logger.info(f"User {uid} (SID: {request.sid}) disconnected. Cleaning up their rooms.")

            for room_id_key in list(rooms.keys()):
                room = find_room(rooms, room_id_key)

                if room and uid in room.current_users:
                    _handle_user_departure(socketio, room_id_key, uid)
        else:
            logger.info(f"SID {request.sid} disconnected, no user mapping found or already cleaned up.")

    @socketio.on("join_room")
    def on_join(data):
        room_id = int(data.get("room_id"))
        uid = data.get("uid")
        sid_map[uid] = request.sid
        uid_map[request.sid] = uid
        join_room(room_id)

        if find_room(rooms, room_id) != None:
            if uid not in rooms[room_id].current_users:
                rooms[room_id].current_users.append(uid)
        else:
            logger.warning(f"Room {room_id} not found")

        logger.info(f"{users[uid].username} joined room {room_id}")
        socketio.emit("user_joined", {"uid": uid}, room=room_id)

    @socketio.on("leave_room")
    def on_leave(data):
        room_id = int(data.get("room_id"))
        uid = data.get("uid")
        del sid_map[uid]
        del uid_map[request.sid]
        leave_room(room_id)

        logger.info(f"{users[uid].username} left room {room_id}")
        _handle_user_departure(socketio, room_id, uid)
            
        


    @socketio.on("send_message")
    def on_message(data):
        room_id = int(data.get("room_id"))
        message_type = data.get("message_type")
        logger.info(f"sent {message_type} from {room_id}")

        match message_type:
            case "msg":
                message = data.get("message")
                socketio.emit("receive_message", {"message": message}, room=room_id)
            case "play":
                socketio.emit("broadcast_play", {}, room=room_id, include_self=False)
            case "pause":
                socketio.emit("broadcast_pause", {}, room=room_id, include_self=False)
            case "sync":
                timestamp = data.get("timestamp");
                socketio.emit("broadcast_sync", {"timestamp": timestamp}, room=room_id, include_self=False)
            case "req_sync":
                host_uid = rooms[room_id].host
                host_sid = sid_map[host_uid]
                socketio.emit("req_sync", {}, to=host_sid)
            case "add":
                video = data.get("video")
                rooms[room_id].queue.append(video)
                socketio.emit("broadcast_add", {"video": video}, room=room_id, include_self=False)
            case "skip":
                logger.info(f"Skipping video: {rooms[room_id].queue[0]}")
                rooms[room_id].current_song = rooms[room_id].queue[0]
                logger.info(f"Current song updated to: {rooms[room_id].current_song}")
                rooms[room_id].queue.pop(0)
                socketio.emit("broadcast_skip", {}, room=room_id, include_self=False)
            case "ping":
                socketio.emit("pong", {}, to=request.sid)
            case _:
                logger.warning(f"Invalid control signal received: '{message_type}' from SID: {request.sid} in Room ID: {room_id}")

