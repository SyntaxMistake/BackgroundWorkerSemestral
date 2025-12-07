#!/usr/bin/env python3
import socket
import threading
import json
import sys
import os

class TicTacToe3DServer:
    def __init__(self, host='0.0.0.0', port=None):
        # Render provides PORT environment variable
        if port is None:
            port = int(os.environ.get('PORT', 5555))
        
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server.bind((host, port))
        except OSError as e:
            print(f"Failed to bind to port {port}: {e}", flush=True)
            print(f"Available ports from Render: {os.environ.get('PORT', 'Not set')}", flush=True)
            raise
        
        self.server.listen(4)
        print(f"Server listening on {host}:{port}", flush=True)
        
        # [Rest of your existing server code remains the same...]

class NetworkClient:
    def __init__(self):
        self.socket = None
        self.connected = False
        self.player_id = None
        self.game_state = None
        self.receive_thread = None
        self.callback = None
        
    def connect(self, host, port, on_state_update):
        """Connect to the server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((host, port))
            self.connected = True
            self.callback = on_state_update
            
            # Start receive thread
            self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.receive_thread.start()
            
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def send(self, data):
        """Send data to server"""
        if self.connected:
            try:
                self.socket.send((json.dumps(data) + "\n").encode())
            except:
                self.connected = False
    
    def receive_loop(self):
        """Receive messages from server"""
        buffer = ""
        while self.connected:
            try:
                data = self.socket.recv(4096).decode()
                if not data:
                    break
                buffer += data
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        message = json.loads(line)
                        self.handle_message(message)
            except:
                break
    
    def handle_message(self, message):
        """Handle incoming messages"""
        msg_type = message.get('type')
        
        if msg_type == 'init':
            self.player_id = message.get('player_id')
            print(f"Connected as Player {self.player_id + 1}")
            
        elif msg_type == 'state':
            self.game_state = message
            if self.callback:
                self.callback(message)
    
    def make_move(self, z, y, x):
        """Send move to server"""
        if self.connected and self.player_id is not None:
            self.send({
                'type': 'move',
                'player': self.player_id,
                'z': z, 'y': y, 'x': x
            })
    
    def disconnect(self):
        """Disconnect from server"""
        self.connected = False
        if self.socket:
            self.socket.close()

if __name__ == "__main__":
    # Render-specific: Get host/port from environment
    host = os.environ.get('HOST', '0.0.0.0')
    port_env = os.environ.get('PORT')
    
    if port_env:
        port = int(port_env)
    else:
        # For local development
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
    
    server = TicTacToe3DServer(host, port)
    server.run()