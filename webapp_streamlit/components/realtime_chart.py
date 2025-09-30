#!/usr/bin/env python3
"""
Real-time Chart Component for Streamlit Dashboard
Forex-style real-time charts với WebSocket integration

Chức năng:
- WebSocket connection đến FastAPI server
- Real-time data updates không cần refresh
- Forex-style interactive charts với Plotly
- Auto-scaling và smooth animations
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import json
import asyncio
import websockets
import time
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class RealTimeChart:
    """
    Component để hiển thị real-time charts với WebSocket updates
    """
    
    def __init__(self, websocket_url: str = "ws://facebook-monitor-api:8000/ws"):
        """
        Khởi tạo RealTimeChart
        
        Args:
            websocket_url: URL của WebSocket server
        """
        self.websocket_url = websocket_url
        self.client_id = f"streamlit_{int(time.time())}"
        self.websocket = None
        self.is_connected = False
        self.data_buffer = {}  # Buffer data cho mỗi post
        self.last_update = {}  # Timestamp update cuối cho mỗi post
        
        # Chart configuration
        self.chart_config = {
            'template': 'plotly_dark',
            'height': 400,
            'animation_duration': 500,
            'max_points': 100  # Giới hạn số điểm trên chart
        }
    
    def create_forex_style_chart(self, post_signature: str, data: List[Dict]) -> go.Figure:
        """
        Tạo forex-style chart cho một post
        
        Args:
            post_signature: Signature của post
            data: List interaction data
            
        Returns:
            Plotly Figure object
        """
        if not data:
            # Empty chart
            fig = go.Figure()
            fig.update_layout(
                title=f"Real-time Engagement - {post_signature[:20]}...",
                template=self.chart_config['template'],
                height=self.chart_config['height'],
                xaxis_title="Time",
                yaxis_title="Engagement Count",
                showlegend=True
            )
            return fig
        
        # Prepare data
        df = pd.DataFrame(data)
        df['log_timestamp_utc'] = pd.to_datetime(df['log_timestamp_utc'])
        df = df.sort_values('log_timestamp_utc')
        
        # Limit số điểm để performance tốt
        if len(df) > self.chart_config['max_points']:
            df = df.tail(self.chart_config['max_points'])
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=('Likes & Comments', 'Total Engagement'),
            row_heights=[0.7, 0.3]
        )
        
        # Main chart - Likes và Comments
        fig.add_trace(
            go.Scatter(
                x=df['log_timestamp_utc'],
                y=df['like_count'],
                mode='lines+markers',
                name='Likes',
                line=dict(color='#00ff88', width=2),
                marker=dict(size=4),
                hovertemplate='<b>Likes</b><br>Time: %{x}<br>Count: %{y}<extra></extra>'
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=df['log_timestamp_utc'],
                y=df['comment_count'],
                mode='lines+markers',
                name='Comments',
                line=dict(color='#ff6b6b', width=2),
                marker=dict(size=4),
                hovertemplate='<b>Comments</b><br>Time: %{x}<br>Count: %{y}<extra></extra>'
            ),
            row=1, col=1
        )
        
        # Secondary chart - Total engagement
        df['total_engagement'] = df['like_count'] + df['comment_count']
        fig.add_trace(
            go.Scatter(
                x=df['log_timestamp_utc'],
                y=df['total_engagement'],
                mode='lines',
                name='Total',
                line=dict(color='#4ecdc4', width=3),
                fill='tozeroy',
                fillcolor='rgba(78, 205, 196, 0.1)',
                hovertemplate='<b>Total Engagement</b><br>Time: %{x}<br>Count: %{y}<extra></extra>'
            ),
            row=2, col=1
        )
        
        # Update layout cho forex-style
        fig.update_layout(
            title={
                'text': f"📈 Real-time Engagement - {post_signature[:20]}...",
                'x': 0.5,
                'xanchor': 'center',
                'font': {'size': 16, 'color': 'white'}
            },
            template=self.chart_config['template'],
            height=self.chart_config['height'],
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=0, r=0, t=60, b=0),
            hovermode='x unified',
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        
        # Update xaxis
        fig.update_xaxes(
            showgrid=True,
            gridcolor='rgba(128, 128, 128, 0.2)',
            showline=True,
            linecolor='rgba(128, 128, 128, 0.3)'
        )
        
        # Update yaxis
        fig.update_yaxes(
            showgrid=True,
            gridcolor='rgba(128, 128, 128, 0.2)',
            showline=True,
            linecolor='rgba(128, 128, 128, 0.3)'
        )
        
        return fig
    
    def create_system_overview_chart(self, stats: Dict) -> go.Figure:
        """
        Tạo system overview chart
        
        Args:
            stats: System statistics
            
        Returns:
            Plotly Figure object
        """
        # Create metrics cards style chart
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('Active Posts', 'Queue Status', 'Interactions Today', 'System Health'),
            specs=[[{"type": "indicator"}, {"type": "bar"}],
                   [{"type": "indicator"}, {"type": "pie"}]]
        )
        
        # Active Posts indicator
        fig.add_trace(
            go.Indicator(
                mode="number+gauge+delta",
                value=stats.get('tracking_posts', 0),
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Active Posts"},
                gauge={
                    'axis': {'range': [None, 1000]},
                    'bar': {'color': "#00ff88"},
                    'bgcolor': "rgba(0,0,0,0.1)",
                    'bordercolor': "rgba(255,255,255,0.3)"
                }
            ),
            row=1, col=1
        )
        
        # Queue status
        queue_data = {
            'High-Freq': stats.get('high_freq_update_queue_length', 0),
            'Low-Freq': stats.get('low_freq_update_queue_length', 0),  
            'Discovery': stats.get('discovery_queue_length', 0)
        }
        
        fig.add_trace(
            go.Bar(
                x=list(queue_data.keys()),
                y=list(queue_data.values()),
                marker_color=['#ff6b6b', '#4ecdc4', '#45b7d1'],
                name="Queue Length"
            ),
            row=1, col=2
        )
        
        # Today interactions
        fig.add_trace(
            go.Indicator(
                mode="number+delta",
                value=stats.get('today_interactions', 0),
                title={'text': "Today Interactions"},
                delta={'reference': stats.get('yesterday_interactions', 0)}
            ),
            row=2, col=1
        )
        
        # System health pie
        health_data = {
            'Tracking': stats.get('tracking_posts', 0),
            'Expired': stats.get('expired_posts', 0)
        }
        
        fig.add_trace(
            go.Pie(
                labels=list(health_data.keys()),
                values=list(health_data.values()),
                marker_colors=['#00ff88', '#ff6b6b'],
                name="Post Status"
            ),
            row=2, col=2
        )
        
        fig.update_layout(
            title={
                'text': "📊 System Overview",
                'x': 0.5,
                'xanchor': 'center'
            },
            template=self.chart_config['template'],
            height=500,
            showlegend=False
        )
        
        return fig
    
    async def connect_websocket(self):
        """Kết nối đến WebSocket server"""
        try:
            full_url = f"{self.websocket_url}/{self.client_id}"
            self.websocket = await websockets.connect(full_url)
            self.is_connected = True
            logger.info(f"✅ WebSocket connected: {full_url}")
            return True
            
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            self.is_connected = False
            return False
    
    async def subscribe_to_post(self, post_signature: str):
        """Subscribe đến updates của một post"""
        if not self.websocket or not self.is_connected:
            return False
        
        try:
            message = {
                "command": "subscribe_post",
                "post_signature": post_signature
            }
            
            await self.websocket.send(json.dumps(message))
            logger.info(f"📊 Subscribed to post: {post_signature[:20]}...")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to subscribe to post: {e}")
            return False
    
    async def get_system_stats(self):
        """Request system statistics"""
        if not self.websocket or not self.is_connected:
            return False
        
        try:
            message = {"command": "get_system_stats"}
            await self.websocket.send(json.dumps(message))
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to get system stats: {e}")
            return False
    
    async def listen_for_updates(self):
        """Listen for WebSocket updates"""
        if not self.websocket or not self.is_connected:
            return
        
        try:
            async for message in self.websocket:
                data = json.loads(message)
                message_type = data.get("type")
                
                if message_type == "post_data":
                    # Initial post data
                    post_signature = data.get("post_signature")
                    interactions = data.get("interactions", [])
                    
                    self.data_buffer[post_signature] = interactions
                    self.last_update[post_signature] = time.time()
                    
                elif message_type == "post_update":
                    # Real-time update
                    post_signature = data.get("post_signature") 
                    update_data = data.get("data", {})
                    
                    if post_signature in self.data_buffer:
                        # Add new interaction to buffer
                        if "interaction" in update_data:
                            self.data_buffer[post_signature].append(update_data["interaction"])
                            
                            # Limit buffer size
                            if len(self.data_buffer[post_signature]) > self.chart_config['max_points']:
                                self.data_buffer[post_signature] = self.data_buffer[post_signature][-self.chart_config['max_points']:]
                        
                        self.last_update[post_signature] = time.time()
                
                elif message_type == "system_stats":
                    # System statistics update
                    self.system_stats = data.get("data", {})
                    self.last_stats_update = time.time()
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("⚠️ WebSocket connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"❌ Error listening for updates: {e}")
            self.is_connected = False
    
    def disconnect(self):
        """Disconnect WebSocket"""
        if self.websocket:
            try:
                asyncio.create_task(self.websocket.close())
            except (asyncio.CancelledError, ConnectionError, Exception):
                pass
        
        self.is_connected = False
        logger.info("🔌 WebSocket disconnected")


def create_realtime_chart_component():
    """
    Streamlit component cho real-time charts
    """
    # Initialize session state
    if 'realtime_chart' not in st.session_state:
        st.session_state.realtime_chart = RealTimeChart()
    
    chart = st.session_state.realtime_chart
    
    # UI Controls
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.markdown("### 📈 Real-time Post Monitoring")
    
    with col2:
        if st.button("🔌 Connect WebSocket"):
            if asyncio.run(chart.connect_websocket()):
                st.success("Connected!")
                # Start listening in background
                asyncio.create_task(chart.listen_for_updates())
            else:
                st.error("Connection failed!")
    
    with col3:
        connection_status = "🟢 Connected" if chart.is_connected else "🔴 Disconnected"
        st.markdown(f"**Status:** {connection_status}")
    
    # Post selection
    post_signature = st.text_input(
        "Post Signature to Monitor",
        placeholder="Enter post signature...",
        help="Enter the post signature you want to monitor in real-time"
    )
    
    if post_signature and st.button("📊 Subscribe to Post"):
        if chart.is_connected:
            if asyncio.run(chart.subscribe_to_post(post_signature)):
                st.success(f"Subscribed to {post_signature[:20]}...")
        else:
            st.error("Please connect WebSocket first!")
    
    # Display charts
    if post_signature and post_signature in chart.data_buffer:
        # Real-time chart cho post
        chart_data = chart.data_buffer[post_signature]
        fig = chart.create_forex_style_chart(post_signature, chart_data)
        
        # Auto-refresh chart
        chart_placeholder = st.empty()
        with chart_placeholder.container():
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{post_signature}")
        
        # Show last update time
        if post_signature in chart.last_update:
            last_update = datetime.fromtimestamp(chart.last_update[post_signature])
            st.caption(f"Last update: {last_update.strftime('%H:%M:%S')}")
    
    # System overview
    if hasattr(chart, 'system_stats'):
        st.markdown("---")
        st.markdown("### 📊 System Overview")
        
        stats_fig = chart.create_system_overview_chart(chart.system_stats)
        st.plotly_chart(stats_fig, use_container_width=True, key="system_overview")


def create_forex_dashboard():
    """
    Tạo forex-style dashboard với multiple charts
    """
    st.set_page_config(
        page_title="Real-time Facebook Monitor",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Custom CSS cho forex-style
    st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(90deg, #1e3c72 0%, #2a5298 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #00ff88;
    }
    
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.8;
    }
    
    .status-connected {
        color: #00ff88;
        font-weight: bold;
    }
    
    .status-disconnected {
        color: #ff6b6b;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("📈 Real-time Facebook Post Monitor")
    st.markdown("*Enterprise Edition - Forex-style Real-time Dashboard*")
    
    # Main real-time chart component
    create_realtime_chart_component()


# Test function
if __name__ == "__main__":
    create_forex_dashboard()




